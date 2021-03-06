import re
import urllib
import logging
from abc import abstractmethod

import requests

from .exceptions import VkAuthError, VkAPIError
from .exceptions import CAPTCHA_IS_NEEDED as CAPTCHA_IS_NEEDED
from .exceptions import ACCESS_DENIED as ACCESS_DENIED
from .api import APINamespace
from .utils import json_iter_parse, stringify

logger = logging.getLogger('vk')

class SilentAPI:
    METHOD_COMMON_PARAMS = {'v', 'lang', 'https', 'test_mode'}
    API_URL = 'https://api.vk.com/method/'
    CAPTCHA_URL = 'https://m.vk.com/captcha.php'

    def __new__(cls, *args, **kwargs):
        method_common_params = {key: kwargs.pop(key) for key in tuple(kwargs) if key in cls.METHOD_COMMON_PARAMS}
        api = object.__new__(cls)
        api.__init__(*args, **kwargs)
        return APINamespace(api, method_common_params)

    def __init__(self, timeout=10):
        self.access_token = None
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers['Accept'] = 'application/json'
        self.session.headers['Content-Type'] = 'application/x-www-form-urlencoded'

    def send(self, request):
        logger.debug('Prepare API Method request')
        self.prepare_request(request)
        method_url = self.API_URL + request.method
        response = self.session.post(method_url, request.method_params, timeout=self.timeout)
        # Make sure we don't have any generic HTTP errors.
        try:
            response.raise_for_status()
        except Exception as e: 
            yield e
            return
        # Split the incoming stream of JSON dictionaries 
        # or arrays into conceise separate objects.
        for resp in json_iter_parse(response.text):
            if 'error' in resp:
                yield VkAPIError(resp['error'])                
            elif 'response' in resp:
                yield resp['response']

    @abstractmethod
    def prepare_request(self, request):
        if self.access_token is not None:
            request.method_params['access_token'] = self.access_token

class LoudAPI(SilentAPI):

    def send(self, request):
        for resp in SilentAPI.send(self, request):
            if isinstance(resp, VkAPIError):                
                # if resp.code == CAPTCHA_IS_NEEDED:
                #     request.method_params['captcha_key'] = self.get_captcha_key(request)
                #     request.method_params['captcha_sid'] = request.api_error.captcha_sid
                #     yield from self.send(request)
                # elif resp.code == ACCESS_DENIED:
                #     self.access_token = self.get_access_token()
                #     yield from self.send(request)
                # else:
                #     raise resp
                raise resp
            elif isinstance(resp, Exception):
                raise resp
            else:
                yield resp


    def get_access_token(self):
        raise NotImplementedError

    def get_captcha_key(self, request):
        raise NotImplementedError


class API(LoudAPI):
    def __init__(self, access_token, **kwargs):
        super().__init__(**kwargs)
        self.access_token = access_token


class UserAPI(LoudAPI):
    LOGIN_URL = 'https://m.vk.com'
    AUTHORIZE_URL = 'https://oauth.vk.com/authorize'

    def __init__(self, user_login='', user_password='', app_id=None, scope='offline', **kwargs):
        super().__init__(**kwargs)

        self.user_login = user_login
        self.user_password = user_password
        self.app_id = app_id
        self.scope = scope

        self.access_token = self.get_access_token()

    @staticmethod
    def get_form_action(response):
        form_action = re.findall(r'<form(?= ).* action="(.+)"', response.text)
        if form_action:
            return form_action[0]
        else:
            raise VkAuthError('No form on page {}'.format(response.url))

    def get_response_url_queries(self, response):
        if not response.ok:
            if response.status_code == 401:
                raise VkAuthError(response.json()['error_description'])
            else:
                response.raise_for_status()

        return self.get_url_queries(response.url)

    @staticmethod
    def get_url_queries(url):
        parsed_url = urllib.parse.urlparse(url)
        url_queries = urllib.parse.parse_qsl(parsed_url.fragment)
        # We lose repeating keys values
        return dict(url_queries)

    def get_access_token(self):
        auth_session = requests.Session()

        if self.login(auth_session):
            return self.authorize(auth_session)

    def get_login_form_data(self):
        return {
            'email': self.user_login,
            'pass': self.user_password,
        }

    def login(self, auth_session):
        # Get login page
        login_page_response = auth_session.get(self.LOGIN_URL)
        # Get login form action. It must contains ip_h and lg_h values
        login_action = self.get_form_action(login_page_response)
        # Login using user credentials
        login_response = auth_session.post(login_action, self.get_login_form_data())

        if 'remixsid' in auth_session.cookies or 'remixsid6' in auth_session.cookies:
            return True

        url_queries = self.get_url_queries(login_response.url)
        if 'sid' in url_queries:
            self.auth_captcha_is_needed(login_response)

        elif url_queries.get('act') == 'authcheck':
            self.auth_check_is_needed(login_response.text)

        elif 'security_check' in url_queries:
            self.phone_number_is_needed(login_response.text)

        else:
            raise VkAuthError('Login error (e.g. incorrect password)')

    def get_auth_params(self):
        return {
            'client_id': self.app_id,
            'scope': self.scope,
            'display': 'mobile',
            'response_type': 'token',
        }

    def authorize(self, auth_session):
        """
        OAuth2
        """
        # Ask access
        ask_access_response = auth_session.post(self.AUTHORIZE_URL, self.get_auth_params())
        url_queries = self.get_response_url_queries(ask_access_response)

        if 'access_token' not in url_queries:
            # Grant access
            grant_access_action = self.get_form_action(ask_access_response)
            grant_access_response = auth_session.post(grant_access_action)
            url_queries = self.get_response_url_queries(grant_access_response)

        return self.process_auth_url_queries(url_queries)

    def process_auth_url_queries(self, url_queries):
        self.expires_in = url_queries.get('expires_in')
        self.user_id = url_queries.get('user_id')
        return url_queries.get('access_token')


class CommunityAPI(UserAPI):
    def __init__(self, *args, **kwargs):
        self.group_ids = kwargs.pop('group_ids', None)
        self.default_group_id = None

        self.access_tokens = {}

        super().__init__(*args, **kwargs)

    def get_auth_params(self):
        auth_params = super().get_auth_params()
        auth_params['group_ids'] = stringify(self.group_ids)
        return auth_params

    def process_auth_url_queries(self, url_queries):
        super().process_auth_url_queries(url_queries)

        self.access_tokens = {}
        for key, value in url_queries.items():
            # access_token_GROUP-ID: ACCESS-TOKEN
            if key.startswith('access_token_'):
                group_id = int(key[len('access_token_'):])
                self.access_tokens[group_id] = value

        self.default_group_id = self.group_ids[0]

    def prepare_request(self, request):
        group_id = request.method_params.get('group_id', self.default_group_id)
        request.method_params['access_token'] = self.access_tokens[group_id]


class InteractiveMixin:

    def get_user_login(self):
        user_login = input('VK user login: ')
        return user_login.strip()

    def get_user_password(self):
        import getpass

        user_password = getpass.getpass('VK user password: ')
        return user_password

    def get_access_token(self):
        logger.debug('InteractiveMixin.get_access_token()')
        access_token = super().get_access_token()
        if not access_token:
            access_token = input('VK API access token: ')
        return access_token

    def get_captcha_key(self, captcha_image_url):
        """
        Read CAPTCHA key from shell
        """
        print('Open CAPTCHA image url: ', captcha_image_url)
        captcha_key = input('Enter CAPTCHA key: ')
        return captcha_key

    def get_auth_check_code(self):
        """
        Read Auth code from shell
        """
        auth_check_code = input('Auth check code: ')
        return auth_check_code.strip()
