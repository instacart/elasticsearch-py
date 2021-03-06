import time
import urllib3
from urllib3.exceptions import ReadTimeoutError, SSLError as UrllibSSLError
import warnings

from .base import Connection
from ..exceptions import ConnectionError, ImproperlyConfigured, ConnectionTimeout, SSLError
from ..compat import urlencode

class Urllib3HttpConnection(Connection):
    """
    Default connection class using the `urllib3` library and the http protocol.

    :arg http_auth: optional http auth information as either ':' separated
        string or a tuple
    :arg use_ssl: use ssl for the connection if `True`
    :arg verify_certs: whether to verify SSL certificates
    :arg ca_certs: optional path to CA bundle. See
        http://urllib3.readthedocs.org/en/latest/security.html#using-certifi-with-urllib3
        for instructions how to get default set
    :arg client_cert: path to the file containing the private key and the
        certificate
    :arg maxsize: the maximum number of connections which will be kept open to
        this host.
    """
    def __init__(self, host='localhost', port=9200, http_auth=None,
            use_ssl=False, verify_certs=False, ca_certs=None, client_cert=None,
            maxsize=10, **kwargs):

        super(Urllib3HttpConnection, self).__init__(host=host, port=port, **kwargs)
        self.headers = urllib3.make_headers(keep_alive=True)
        if http_auth is not None:
            if isinstance(http_auth, (tuple, list)):
                http_auth = ':'.join(http_auth)
            self.headers.update(urllib3.make_headers(basic_auth=http_auth))

        pool_class = urllib3.HTTPConnectionPool
        kw = {}
        if use_ssl:
            pool_class = urllib3.HTTPSConnectionPool

            if verify_certs:
                kw['cert_reqs'] = 'CERT_REQUIRED'
                kw['ca_certs'] = ca_certs
                kw['cert_file'] = client_cert
            elif ca_certs:
                raise ImproperlyConfigured("You cannot pass CA certificates when verify SSL is off.")
            else:
                warnings.warn(
                    'Connecting to %s using SSL with verify_certs=False is insecure.' % host)

        self.pool = pool_class(host, port=port, timeout=self.timeout, maxsize=maxsize, **kw)

    def perform_request(self, method, url, params=None, body=None, timeout=None, ignore=()):
        url = self.url_prefix + url
        if params:
            url = '%s?%s' % (url, urlencode(params))
        full_url = self.host + url

        start = time.time()
        try:
            kw = {}
            if timeout:
                kw['timeout'] = timeout

            # in python2 we need to make sure the url and method are not
            # unicode. Otherwise the body will be decoded into unicode too and
            # that will fail (#133, #201).
            if not isinstance(url, str):
                url = url.encode('utf-8')
            if not isinstance(method, str):
                method = method.encode('utf-8')

            response = self.pool.urlopen(method, url, body, retries=False, headers=self.headers, **kw)
            duration = time.time() - start
            raw_data = response.data.decode('utf-8')
        except UrllibSSLError as e:
            self.log_request_fail(method, full_url, body, time.time() - start, exception=e)
            raise SSLError('N/A', str(e), e)
        except ReadTimeoutError as e:
            self.log_request_fail(method, full_url, body, time.time() - start, exception=e)
            raise ConnectionTimeout('TIMEOUT', str(e), e)
        except Exception as e:
            self.log_request_fail(method, full_url, body, time.time() - start, exception=e)
            raise ConnectionError('N/A', str(e), e)

        if not (200 <= response.status < 300) and response.status not in ignore:
            self.log_request_fail(method, url, body, duration, response.status)
            self._raise_error(response.status, raw_data)

        self.log_request_success(method, full_url, url, body, response.status,
            raw_data, duration)

        return response.status, response.getheaders(), raw_data

