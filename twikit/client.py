from __future__ import annotations

import io
import json
import os
from typing import Literal

from fake_useragent import UserAgent
from httpx import Response

from .errors import raise_exceptions_from_response, CouldNotTweet
from .group import Group, GroupMessage
from .http import HTTPClient
from .list import List
from .message import Message
from .trend import Trend
from .tweet import ScheduledTweet, Tweet
from .user import User
from .utils import (
    LIST_FEATURES,
    FEATURES,
    TOKEN,
    USER_FEATURES,
    Endpoint,
    Result,
    find_dict,
    get_query_id,
    urlencode
)


class Client:
    """
    A client for interacting with the Twitter API.

    Examples
    --------
    >>> client = Client(language='en-US')

    >>> client.login(
    ...     auth_info_1='example_user',
    ...     auth_info_2='email@example.com',
    ...     password='00000000'
    ... )
    """

    def __init__(self, language: str, **kwargs) -> None:
        self._token = TOKEN
        self.language = language
        self.http = HTTPClient(**kwargs)
        self._user_id = None
        self._user_agent = UserAgent().random

    def _get_guest_token(self) -> str:
        headers = self._base_headers
        headers.pop('X-Twitter-Active-User')
        headers.pop('X-Twitter-Auth-Type')
        response = self.http.post(
            Endpoint.GUEST_TOKEN,
            headers=headers,
            data={}
        ).json()
        guest_token = response['guest_token']
        return guest_token

    @property
    def _base_headers(self) -> dict[str, str]:
        """
        Base headers for Twitter API requests.
        """
        headers = {
            'authorization': f'Bearer {self._token}',
            'content-type': 'application/json',
            'Accept-Language': self.language,
            'X-Twitter-Auth-Type': 'OAuth2Session',
            'X-Twitter-Active-User': 'yes',
            'X-Twitter-Client-Language': self.language,
            'Referer': 'https://twitter.com/',
            'User-Agent': self._user_agent,
        }

        csrf_token = self._get_csrf_token()
        if csrf_token is not None:
            headers['X-Csrf-Token'] = csrf_token
        return headers

    def _get_csrf_token(self) -> str:
        """
        Retrieves the Cross-Site Request Forgery (CSRF) token from the
        current session's cookies.

        Returns
        -------
        str
            The CSRF token as a string.
        """
        return self.http.client.cookies.get('ct0')

    def login(
        self,
        *,
        auth_info_1: str,
        auth_info_2: str | None = None,
        password: str,
    ) -> dict:
        """
        Logs into the account using the specified login information.
        `auth_info_1` and `password` are required parameters.
        `auth_info_2` is optional and can be omitted, but it is
        recommended to provide if available.
        The order in which you specify authentication information
        (auth_info_1 and auth_info_2) is flexible.

        Parameters
        ----------
        auth_info_1 : str
            The first piece of authentication information,
            which can be a username, email address, or phone number.
        auth_info_2 : str, default=None
            The second piece of authentication information,
            which is optional but recommended to provide.
            It can be a username, email address, or phone number.
        password : str
            The password associated with the account.

        Examples
        --------
        >>> client.login(
        ...     auth_info_1='example_user',
        ...     auth_info_2='email@example.com',
        ...     password='00000000'
        ... )
        """
        guest_token = self._get_guest_token()
        headers = self._base_headers | {
            'x-guest-token': guest_token
        }
        headers.pop('X-Twitter-Active-User')
        headers.pop('X-Twitter-Auth-Type')

        def _execute_task(
            flow_token: str | None = None,
            subtask_input: dict | None = None,
            flow_name: str | None = None
        ) -> dict:
            url = Endpoint.TASK
            if flow_name is not None:
                url += f'?flow_name={flow_name}'

            data = {}
            if flow_token is not None:
                data['flow_token'] = flow_token
            if subtask_input is not None:
                data['subtask_inputs'] = [subtask_input]

            response = self.http.post(
                url, data=json.dumps(data), headers=headers
            ).json()
            return response

        flow_token = _execute_task(flow_name='login')['flow_token']
        flow_token = _execute_task(flow_token)['flow_token']
        response = _execute_task(
            flow_token,
            {
                'subtask_id': 'LoginEnterUserIdentifierSSO',
                'settings_list': {
                    'setting_responses': [
                        {
                            'key': 'user_identifier',
                            'response_data': {
                                'text_data': {'result': auth_info_1}
                            }
                        }
                    ],
                    'link': 'next_link'
                }
            }
        )

        flow_token = response['flow_token']
        task_id = response['subtasks'][0]['subtask_id']

        if task_id == 'LoginEnterAlternateIdentifierSubtask':
            response = _execute_task(
                flow_token,
                {
                    'subtask_id': 'LoginEnterAlternateIdentifierSubtask',
                    'enter_text': {
                        'text': auth_info_2,
                        'link': 'next_link'
                    }
                }
            )
            flow_token = response['flow_token']

        response = _execute_task(
            flow_token,
            {
                'subtask_id': 'LoginEnterPassword',
                'enter_password': {
                    'password': password,
                    'link': 'next_link'
                }
            }
        )

        flow_token = response['flow_token']

        response = _execute_task(
            flow_token,
            {
                'subtask_id': 'AccountDuplicationCheck',
                'check_logged_in_account': {
                    'link': 'AccountDuplicationCheck_false'
                }
            },
        )

        if not response['subtasks']:
            return
        flow_token = response['flow_token']
        task_id = response['subtasks'][0]['subtask_id']
        self._user_id = find_dict(response, 'id_str')[0]

        if task_id == 'LoginAcid':
            print(find_dict(response, 'secondary_text')[0]['text'])
            response = _execute_task(
                flow_token,
                {
                    'subtask_id': 'LoginAcid',
                    'enter_text': {
                        'text': input('>>> '),
                        'link': 'next_link'
                    }
                }
            )

        return response

    def logout(self) -> Response:
        """
        Logs out of the currently logged-in account.
        """
        response = self.http.post(
            Endpoint.LOGOUT,
            headers=self._base_headers
        )
        return response

    def user_id(self) -> str:
        """
        Retrieves the user ID associated with the authenticated account.
        """
        if self._user_id is not None:
            return self._user_id
        response = self.http.get(
            Endpoint.ALL,
            headers=self._base_headers
        ).json()
        user_id = find_dict(response, 'id_str')[0]
        self._user_id = user_id
        return user_id

    def user(self) -> User:
        """
        Retrieve detailed information about the authenticated user.
        """
        return self.get_user_by_id(self.user_id())

    def get_cookies(self) -> dict:
        """
        Get the cookies.
        You can skip the login procedure by loading the saved cookies
        using the :func:`set_cookies` method.

        Examples
        --------
        >>> client.get_cookies()

        See Also
        --------
        .set_cookies
        .load_cookies
        .save_cookies
        """
        return dict(self.http.client.cookies)

    def save_cookies(self, path: str) -> None:
        """
        Save cookies to file in json format.
        You can skip the login procedure by loading the saved cookies
        using the :func:`load_cookies` method.

        Parameters
        ----------
        path : str
            The path to the file where the cookie will be stored.

        Examples
        --------
        >>> client.save_cookies('cookies.json')

        See Also
        --------
        .load_cookies
        .get_cookies
        .set_cookies
        """
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.get_cookies(), f)

    def set_cookies(self, cookies: dict, clear_cookies: bool = False) -> None:
        """
        Sets cookies.
        You can skip the login procedure by loading a saved cookies.

        Parameters
        ----------
        cookies : dict
            The cookies to be set as key value pair.

        Examples
        --------
        >>> with open('cookies.json', 'r', encoding='utf-8') as f:
        ...     client.set_cookies(json.load(f))

        See Also
        --------
        .get_cookies
        .load_cookies
        .save_cookies
        """
        if clear_cookies:
            self.http.client.cookies.clear()
        self.http.client.cookies.update(cookies)

    def load_cookies(self, path: str) -> None:
        """
        Loads cookies from a file.
        You can skip the login procedure by loading a saved cookies.

        Parameters
        ----------
        path : str
            Path to the file where the cookie is stored.

        Examples
        --------
        >>> client.load_cookies('cookies.json')

        See Also
        --------
        .get_cookies
        .save_cookies
        .set_cookies
        """
        with open(path, 'r', encoding='utf-8') as f:
            self.set_cookies(json.load(f))

    def _search(
        self,
        query: str,
        product: str,
        count: int,
        cursor: str | None
    ) -> dict:
        """
        Base search function.
        """
        variables = {
            'rawQuery': query,
            'count': count,
            'querySource': 'typed_query',
            'product': product
        }
        if cursor is not None:
            variables['cursor'] = cursor
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(FEATURES)
        }
        response = self.http.get(
            Endpoint.SEARCH_TIMELINE,
            params=params,
            headers=self._base_headers
        ).json()

        return response

    def search_tweet(
        self,
        query: str,
        product: Literal['Top', 'Latest', 'Media'],
        count: int = 20,
        cursor: str | None = None
    ) -> Result[Tweet]:
        """
        Searches for tweets based on the specified query and
        product type.

        Parameters
        ----------
        query : str
            The search query.
        product : {'Top', 'Latest', 'Media'}
            The type of tweets to retrieve.
        count : int, default=20
            The number of tweets to retrieve, between 1 and 20.
        cursor : str, default=20
            Token to retrieve more tweets.

        Returns
        -------
        Result[Tweet]
            An instance of the `Result` class containing the
            search results.

        Examples
        --------
        >>> tweets = client.search_tweet('query', 'Top')
        >>> for tweet in tweets:
        ...    print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        >>> more_tweets = tweets.next()  # Retrieve more tweets
        >>> for tweet in more_tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        """
        product = product.capitalize()

        response = self._search(query, product, count, cursor)
        instructions = find_dict(response, 'instructions')[0]

        if cursor is None and product == 'Media':
            items = instructions[-1]['entries'][0]['content']['items']
            next_cursor = instructions[-1]['entries'][-1]['content']['value']
        elif cursor is None:
            items = instructions[-1]['entries']
            next_cursor = items[-1]['content']['value']
        elif product == 'Media':
            items = instructions[0]['moduleItems']
            next_cursor = instructions[1]['entries'][1]['content']['value']
        else:
            items = instructions[0]['entries']
            next_cursor = instructions[-1]['entry']['content']['value']

        results = []
        for item in items:
            if product != 'Media' and 'itemContent' not in item['content']:
                continue
            tweet_info = find_dict(item, 'result')[0]
            if 'tweet' in tweet_info:
                tweet_info = tweet_info['tweet']
            user_info = tweet_info['core']['user_results']['result']
            results.append(Tweet(self, tweet_info, User(self, user_info)))

        return Result(
            results,
            lambda:self.search_tweet(query, product, count, next_cursor),
            next_cursor
        )

    def search_user(
        self,
        query: str,
        count: int = 20,
        cursor: str | None = None
    ) -> Result[User]:
        """
        Searches for users based on the provided query.

        Parameters
        ----------
        query : str
            The search query for finding users.
        count : int, default=20
            The number of users to retrieve in each request.
        cursor : str, default=None
            Token to retrieve more users.

        Returns
        -------
        Result[User]
            An instance of the `Result` class containing the
            search results.

        Examples
        --------
        >>> result = client.search_user('query')
        >>> for user in result:
        ...     print(user)
        <User id="...">
        <User id="...">
        ...
        ...

        >>> more_results = result.next()  # Retrieve more search results
        >>> for user in more_results:
        ...     print(user)
        <User id="...">
        <User id="...">
        ...
        ...
        """
        response = self._search(query, 'People', count, cursor)
        items = find_dict(response, 'entries')[0]
        next_cursor = items[-1]['content']['value']

        results = []
        for item in items:
            if 'itemContent' not in item['content']:
                continue
            user_info = find_dict(item, 'result')[0]
            results.append(User(self, user_info))

        return Result(
            results,
            lambda:self.search_user(query, count, next_cursor),
            next_cursor
        )

    def upload_media(self, source: str | bytes, index: int) -> int:
        """
        Uploads media to twitter.

        Parameters
        ----------
        media_path : str | bytes
            The file path or binary data of the media to be uploaded.
        index : int
            The index of the media segment being uploaded.
            Should start from 0 and increment by 1 for
            each subsequent upload.

        Returns
        -------
        int
            The media ID of the uploaded media.

        Examples
        --------
        Upload media files in sequence, starting from index 0.

        >>> media_id_1 = client.upload_media('media1.jpg', index=0)
        >>> media_id_2 = client.upload_media('media2.jpg', index=1)
        >>> media_id_3 = client.upload_media('media3.jpg', index=2)
        """
        if isinstance(source, str):
            # If the source is a path
            img_size = os.path.getsize(source)
            binary_stream = open(source, 'rb')
        elif isinstance(source, bytes):
            # If the source is bytes
            img_size = len(source)
            binary_stream = io.BytesIO(source)

        # ============ INIT =============
        params = {
            'command': 'INIT',
            'total_bytes': img_size,
        }
        response = self.http.post(
            Endpoint.UPLOAD_MEDIA,
            params=params,
            headers=self._base_headers
        ).json()
        media_id = response['media_id']
        # =========== APPEND ============
        params = {
            'command': 'APPEND',
            'media_id': media_id,
            'segment_index': index,
        }
        headers = self._base_headers
        headers.pop('content-type')
        files = {
            'media': (
                'blob',
                binary_stream,
                'application/octet-stream',
            )
        }
        response = self.http.post(
            Endpoint.UPLOAD_MEDIA,
            params=params,
            headers=headers,
            files=files
        )
        binary_stream.close()
        # ========== FINALIZE ===========
        params = {
            'command': 'FINALIZE',
            'media_id': media_id,
        }
        response = self.http.post(
            Endpoint.UPLOAD_MEDIA,
            params=params,
            headers=self._base_headers,
        ).json()

        return response['media_id_string']

    def create_poll(
        self,
        choices: list[str],
        duration_minutes: int
    ) -> str:
        """
        Creates a poll and returns card-uri.

        Parameters
        ----------
        choices : list[str]
            A list of choices for the poll. Maximum of 4 choices.
        duration_minutes : int
            The duration of the poll in minutes.

        Returns
        -------
        str
            The URI of the created poll card.

        Examples
        --------
        Create a poll with three choices lasting for 60 minutes:

        >>> choices = ['Option A', 'Option B', 'Option C']
        >>> duration_minutes = 60
        >>> card_uri = client.create_poll(choices, duration_minutes)
        >>> print(card_uri)
        'card://0000000000000000000'
        """
        card_data = {
            'twitter:card': f'poll{len(choices)}choice_text_only',
            'twitter:api:api:endpoint': '1',
            'twitter:long:duration_minutes': duration_minutes
        }

        for i, choice in enumerate(choices, 1):
            card_data[f'twitter:string:choice{i}_label'] = choice

        data = urlencode(
            {'card_data': card_data}
        )
        headers = self._base_headers | {
            'content-type': 'application/x-www-form-urlencoded'
        }
        response = self.http.post(
            Endpoint.CREATE_CARD,
            data=data,
            headers=headers,
        ).json()

        return response['card_uri']

    def create_tweet(
        self,
        text: str = '',
        media_ids: list[str] | None = None,
        poll_uri: str | None = None,
        reply_to: str | None = None,
        conversation_control: Literal[
            'followers', 'verified', 'mentioned'] | None = None
    ) -> Tweet:
        """
        Creates a new tweet on Twitter with the specified
        text, media, and poll.

        Parameters
        ----------
        text : str, default=''
            The text content of the tweet.
        media_ids : list[str], default=None
            A list of media IDs or URIs to attach to the tweet.
            media IDs can be obtained by using the `upload_media` method.
        poll_uri : str, default=None
            The URI of a Twitter poll card to attach to the tweet.
            Poll URIs can be obtained by using the `create_poll` method.
        reply_to : str, default=None
            The ID of the tweet to which this tweet is a reply.
        conversation_control : {'followers', 'verified', 'mentioned'}
            The type of conversation control for the tweet:
            - 'followers': Limits replies to followers only.
            - 'verified': Limits replies to verified accounts only.
            - 'mentioned': Limits replies to mentioned accounts only.

        Raises
        ------
        DuplicateTweet : If the tweet is a duplicate of another tweet.

        Returns
        -------
        Tweet
            The Created Tweet.

        Examples
        --------
        Create a tweet with media:

        >>> tweet_text = 'Example text'
        >>> media_ids = [
        ...     client.upload_media('image1.png', 0),
        ...     client.upload_media('image1.png', 1)
        ... ]
        >>> client.create_tweet(
        ...     tweet_text,
        ...     media_ids=media_ids
        ... )

        Create a tweet with a poll:

        >>> tweet_text = 'Example text'
        >>> poll_choices = ['Option A', 'Option B', 'Option C']
        >>> duration_minutes = 60
        >>> poll_uri = client.create_poll(poll_choices, duration_minutes)
        >>> client.create_tweet(
        ...     tweet_text,
        ...     poll_uri=poll_uri
        ... )

        See Also
        --------
        .upload_media
        .create_poll
        """
        media_entities = [
            {'media_id': media_id, 'tagged_users': []}
            for media_id in (media_ids or [])
        ]
        variables = {
            'tweet_text': text,
            'dark_request': False,
            'media': {
                'media_entities': media_entities,
                'possibly_sensitive': False
            },
            'semantic_annotation_ids': [],
        }

        if poll_uri is not None:
            variables['card_uri'] = poll_uri

        if reply_to is not None:
            variables['reply'] = {
                'in_reply_to_tweet_id': reply_to,
                'exclude_reply_user_ids': []
            }

        if conversation_control is not None:
            conversation_control = conversation_control.lower()
            limit_mode = {
                'followers': 'Community',
                'verified': 'Verified',
                'mentioned': 'ByInvitation'
            }[conversation_control]
            variables['conversation_control'] = {
                'mode': limit_mode
            }

        data = {
            'variables': variables,
            'queryId': get_query_id(Endpoint.CREATE_TWEET),
            'features': FEATURES,
        }
        response = self.http.post(
            Endpoint.CREATE_TWEET,
            data=json.dumps(data),
            headers=self._base_headers,
        ).json()

        _result = find_dict(response, 'result')
        if not _result:
            raise_exceptions_from_response(response['errors'])
            raise CouldNotTweet(
                response['errors'][0]
                if response['errors']
                else 'Failed to post a tweet.'
            )

        tweet_info = _result[0]
        user_info = tweet_info['core']['user_results']['result']
        return Tweet(self, tweet_info, User(self, user_info))

    def create_scheduled_tweet(
        self,
        scheduled_at: int,
        text: str = '',
        media_ids: list[str] | None = None,
    ) -> str:
        """
        Schedules a tweet to be posted at a specified timestamp.

        Parameters
        ----------
        scheduled_at : int
            The timestamp when the tweet should be scheduled for posting.
        text : str, default=''
            The text content of the tweet, by default an empty string.
        media_ids : list[str], default=None
            A list of media IDs to be attached to the tweet, by default None.

        Returns
        -------
        str
            The ID of the scheduled tweet.

        Examples
        --------
        Create a tweet with media:

        >>> scheduled_time = int(time.time()) + 3600  # One hour from now
        >>> tweet_text = 'Example text'
        >>> media_ids = [
        ...     client.upload_media('image1.png', 0),
        ...     client.upload_media('image1.png', 1)
        ... ]
        >>> client.create_scheduled_tweet(
        ...     scheduled_time
        ...     tweet_text,
        ...     media_ids=media_ids
        ... )
        """
        variables = {
            'post_tweet_request': {
            'auto_populate_reply_metadata': False,
            'status': text,
            'exclude_reply_user_ids': [],
            'media_ids': media_ids
            },
            'execute_at': scheduled_at
        }
        data = {
            'variables': variables,
            'queryId': get_query_id(Endpoint.CREATE_SCHEDULED_TWEET),
        }
        response = self.http.post(
            Endpoint.CREATE_SCHEDULED_TWEET,
            data=json.dumps(data),
            headers=self._base_headers,
        ).json()
        return response['data']['tweet']['rest_id']

    def delete_tweet(self, tweet_id: str) -> Response:
        """Deletes a tweet.

        Parameters
        ----------
        tweet_id : str
            ID of the tweet to be deleted.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '0000000000'
        >>> delete_tweet(tweet_id)
        """
        data = {
            'variables': {
                'tweet_id': tweet_id,
                'dark_request': False
            },
            'queryId': get_query_id(Endpoint.DELETE_TWEET)
        }
        response = self.http.post(
            Endpoint.DELETE_TWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def get_user_by_screen_name(self, screen_name: str) -> User:
        """
        Fetches a user by screen name.

        Parameter
        ---------
        screen_name : str
            The screen name of the Twitter user.

        Returns
        -------
        User
            An instance of the User class representing the
            Twitter user.

        Examples
        --------
        >>> target_screen_name = 'example_user'
        >>> user = client.get_user_by_name(target_screen_name)
        >>> print(user)
        <User id="...">
        """
        variables = {
            'screen_name': screen_name,
            'withSafetyModeUserFields': False
        }
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(USER_FEATURES),
            'fieldToggles': json.dumps({'withAuxiliaryUserLabels': False})
        }
        response = self.http.get(
            Endpoint.USER_BY_SCREEN_NAME,
            params=params,
            headers=self._base_headers
        ).json()
        user_data = response['data']['user']['result']
        return User(self, user_data)

    def get_user_by_id(self, user_id: str) -> User:
        """
        Fetches a user by ID

        Parameter
        ---------
        user_id : str
            The ID of the Twitter user.

        Returns
        -------
        User
            An instance of the User class representing the
            Twitter user.

        Examples
        --------
        >>> target_screen_name = '000000000'
        >>> user = client.get_user_by_id(target_screen_name)
        >>> print(user)
        <User id="000000000">
        """
        variables = {
            'userId': user_id,
            'withSafetyModeUserFields': True
        }
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(USER_FEATURES),
        }
        response = self.http.get(
            Endpoint.USER_BY_REST_ID,
            params=params,
            headers=self._base_headers
        ).json()
        user_data = response['data']['user']['result']
        return User(self, user_data)

    def _get_tweet_detail(self, tweet_id: str, cursor: str | None):
        variables = {
            'focalTweetId': tweet_id,
            'with_rux_injections': False,
            'includePromotedContent': True,
            'withCommunity': True,
            'withQuickPromoteEligibilityTweetFields': True,
            'withBirdwatchNotes': True,
            'withVoice': True,
            'withV2Timeline': True
        }
        if cursor is not None:
            variables['cursor'] = cursor
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(FEATURES),
            'fieldToggles': json.dumps({'withAuxiliaryUserLabels': False})
        }
        response = self.http.get(
            Endpoint.TWEET_DETAIL,
            params=params,
            headers=self._base_headers
        ).json()
        return response

    def _get_more_replies(self, tweet_id: str, cursor: str) -> Result[Tweet]:
        response = self._get_tweet_detail(tweet_id, cursor)
        entries = find_dict(response, 'entries')[0]

        results = []
        for entry in entries:
            if entry['entryId'].startswith('cursor'):
                continue
            tweet_info = find_dict(entry, 'result')[0]
            if tweet_info['__typename'] == 'TweetWithVisibilityResults':
                tweet_info = tweet_info['tweet']
            user_info = tweet_info['core']['user_results']['result']
            results.append(Tweet(self, tweet_info, User(self, user_info)))

        if entries[-1]['entryId'].startswith('cursor'):
            next_cursor = entries[-1]['content']['itemContent']['value']
            def _fetch_next_result():
                return self._get_more_replies(tweet_id, next_cursor)
        else:
            next_cursor = None
            _fetch_next_result = None

        return Result(
            results,
            _fetch_next_result,
            next_cursor
        )

    def get_tweet_by_id(
        self, tweet_id: str, cursor: str | None = None
    ) -> Tweet:
        """
        Fetches a tweet by tweet ID.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet.

        Returns
        -------
        Tweet
            A Tweet object representing the fetched tweet.

        Examples
        --------
        >>> target_tweet_id = '...'
        >>> tweet = client.get_tweet_by_id(target_tweet_id)
        >>> print(tweet)
        <Tweet id="...">
        """
        response = self._get_tweet_detail(tweet_id, cursor)
        entries = find_dict(response, 'entries')[0]
        reply_to = []
        replies_list = []
        tweet = None

        for entry in entries:
            if entry['entryId'].startswith('cursor'):
                continue
            
            tweet_info = entry.get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result')
            
            if tweet_info is None:
                continue
            
            if tweet_info['__typename'] == 'TweetWithVisibilityResults':
                tweet_info = tweet_info['tweet']
            user_info = find_dict(tweet_info, 'user_results')[0]['result']
            tweet_object = Tweet(self, tweet_info, User(self, user_info))
            if entry['entryId'] == f'tweet-{tweet_id}':
                tweet = tweet_object
            else:
                if tweet is None:
                    reply_to.append(tweet_object)
                else:
                    replies_list.append(tweet_object)

        if entries[-1]['entryId'].startswith('cursor'):
            # if has more replies
            reply_next_cursor = entries[-1]['content']['itemContent']['value']
            def _fetch_more_replies():
                return self._get_more_replies(tweet_id, reply_next_cursor)
        else:
            reply_next_cursor = None
            _fetch_more_replies = None

        tweet.replies = Result(
            replies_list,
            _fetch_more_replies,
            reply_next_cursor
        )
        tweet.reply_to = reply_to

        return tweet

    def get_scheduled_tweets(self) -> list[ScheduledTweet]:
        """
        Retrieves scheduled tweets.

        Returns
        -------
        list[ScheduledTweet]
            List of ScheduledTweet objects representing the scheduled tweets.
        """
        params = {
            'variables': json.dumps({'ascending': True})
        }
        response = self.http.get(
            Endpoint.FETCH_SCHEDULED_TWEETS,
            params=params,
            headers=self._base_headers
        ).json()
        tweets = find_dict(response, 'scheduled_tweet_list')[0]
        return [ScheduledTweet(self, tweet) for tweet in tweets]

    def delete_scheduled_tweet(self, tweet_id: str) -> Response:
        """
        Delete a scheduled tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the scheduled tweet to delete.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.
        """
        data = {
            'variables': {
                'scheduled_tweet_id': tweet_id
            },
            'queryId': get_query_id(Endpoint.DELETE_SCHEDULED_TWEET)
        }
        response = self.http.post(
            Endpoint.DELETE_SCHEDULED_TWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def _get_tweet_engagements(
        self, tweet_id: str, count: int, cursor: str, endpoint: str,
    ) -> Result[User]:
        """
        Base function to get tweet engagements.
        """
        variables = {
            'tweetId': tweet_id,
            'count': count,
            'includePromotedContent': True
        }
        if cursor is not None:
            variables['cursor'] = cursor
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(FEATURES)
        }
        res = self.http.get(
            endpoint,
            params=params,
            headers=self._base_headers
        )
        response = res.json()
        items = find_dict(response, 'entries')[0]
        next_cursor = items[-1]['content']['value']

        results = []
        for item in items:
            if not item['entryId'].startswith('user'):
                continue
            user_info ={}
            try:
                user_info = find_dict(item, 'result')[0]
                results.append(User(self, user_info))
            except:
                pass

        return Result(
            results,
            lambda:self._get_tweet_engagements(
                tweet_id, count, next_cursor, endpoint),
            next_cursor
        )

    def get_retweeters(
        self, tweet_id: str, count: int = 40, cursor: str | None = None
    ) -> Result[User]:
        """
        Retrieve users who retweeted a specific tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet.
        count : int, default=40
            The maximum number of users to retrieve.
        cursor : str, default=None
            A string indicating the position of the cursor for pagination.

        Returns
        -------
        Result[User]
            A list of users who retweeted the tweet.

        Examples
        --------
        >>> tweet_id = '...'
        >>> retweeters = client.get_retweeters(tweet_id)
        >>> print(retweeters)
        [<User id="...">, <User id="...">, ..., <User id="...">]

        >>> more_retweeters = retweeters.next()  # Retrieve more retweeters.
        >>> print(more_retweeters)
        [<User id="...">, <User id="...">, ..., <User id="...">]
        """
        return self._get_tweet_engagements(
            tweet_id, count, cursor, Endpoint.RETWEETERS
        )

    def get_favoriters(
        self, tweet_id: str, count: int = 40, cursor: str | None = None
    ) -> Result[User]:
        """
        Retrieve users who favorited a specific tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet.
        count : int, default=40
            The maximum number of users to retrieve.
        cursor : str, default=None
            A string indicating the position of the cursor for pagination.

        Returns
        -------
        Result[User]
            A list of users who favorited the tweet.

        Examples
        --------
        >>> tweet_id = '...'
        >>> favoriters = client.get_favoriters(tweet_id)
        >>> print(favoriters)
        [<User id="...">, <User id="...">, ..., <User id="...">]

        >>> more_favoriters = favoriters.next()  # Retrieve more favoriters.
        >>> print(more_favoriters)
        [<User id="...">, <User id="...">, ..., <User id="...">]
        """
        return self._get_tweet_engagements(
            tweet_id, count, cursor, Endpoint.FAVORITERS
        )

    def get_user_tweets(
        self,
        user_id: str,
        tweet_type: Literal['Tweets', 'Replies', 'Media', 'Likes'],
        count: int = 40,
        cursor: str | None = None
    ) -> Result[Tweet]:
        """
        Fetches tweets from a specific user's timeline.

        Parameters
        ----------
        user_id : str
            The ID of the Twitter user whose tweets to retrieve.
            To get the user id from the screen name, you can use
            `get_user_by_screen_name` method.
        tweet_type : {'Tweets', 'Replies', 'Media', 'Likes'}
            The type of tweets to retrieve.
        count : int, default=40
            The number of tweets to retrieve.
        cursor : str, default=None
            The cursor for fetching the next set of results.

        Returns
        -------
        Result[Tweet]
            A Result object containing a list of `Tweet` objects.

        Examples
        --------
        >>> user_id = '...'

        If you only have the screen name, you can get the user id as follows:

        >>> screen_name = 'example_user'
        >>> user = client.get_user_by_screen_name(screen_name)
        >>> user_id = user.id

        >>> tweets = client.get_user_tweets(user_id, 'Tweets', count=20)
        >>> for tweet in tweets:
        ...    print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        >>> more_tweets = tweets.next()  # Retrieve more tweets
        >>> for tweet in more_tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        See Also
        --------
        .get_user_by_screen_name
        """
        tweet_type = tweet_type.capitalize()

        variables = {
            'userId': user_id,
            'count': count,
            'includePromotedContent': True,
            'withQuickPromoteEligibilityTweetFields': True,
            'withVoice': True,
            'withV2Timeline': True
        }
        if cursor is not None:
            variables['cursor'] = cursor
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(FEATURES),
        }

        endpoint = {
            'Tweets': Endpoint.USER_TWEETS,
            'Replies': Endpoint.USER_TWEETS_AND_REPLIES,
            'Media': Endpoint.USER_MEDIA,
            'Likes': Endpoint.USER_LIKES,
        }[tweet_type]

        response = self.http.get(
            endpoint,
            params=params,
            headers=self._base_headers
        ).json()

        instructions = find_dict(response, 'instructions')[0]
        items = instructions[-1]['entries']
        if len(items) <= 2:
            return Result([])
        next_cursor = items[-1]['content']['value']
        if tweet_type == 'Media':
            if cursor is None:
                items = items[0]['content']['items']
            else:
                items = instructions[0]['moduleItems']

        if tweet_type != 'Likes':
            user_info = find_dict(items[0], 'user_results')[-1]['result']
            user = User(self, user_info)

        results = []
        for item in items:
            if (
                tweet_type not in {'Media', 'Replies'}
                and 'itemContent' not in item['content']
            ):
                continue

            if tweet_type == 'Tweets':
                if not item['entryId'].startswith('tweet'):
                    continue

            if tweet_type == 'Replies':
                entry_id = item['entryId']
                if not entry_id.startswith(('profile-conversation', 'tweet')):
                    continue
                if entry_id.startswith('profile-conversation'):
                    item = find_dict(item, 'items')[0][-1]

            tweet_info = find_dict(item, 'result')[0]
            if tweet_info['__typename'] == 'TweetWithVisibilityResults':
                tweet_info = tweet_info['tweet']
            if tweet_type == 'Likes':
                user_info = find_dict(tweet_info, 'result')[0]
                user = User(self, user_info)

            results.append(Tweet(self, tweet_info, user))

        return Result(
            results,
            lambda:self.get_user_tweets(
                user_id, tweet_type, count, next_cursor),
            next_cursor
        )

    def get_timeline(
        self,
        count: int = 20,
        seen_tweet_ids: list[str] | None = None,
        cursor: str | None = None
    ) -> Result[Tweet]:
        """
        Retrieves the timeline.

        Parameters
        ----------
        count : int, default=None
            The number of tweets to retrieve.
        seen_tweet_ids : list[str], default=None
            A list of tweet IDs that have been seen.
        cursor : str, default=None
            A cursor for pagination.

        Returns
        -------
        Result[Tweet]
            A Result object containing a list of Tweet objects.

        Example
        -------
        >>> tweets = client.get_timeline()
        >>> for tweet in tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        >>> more_tweets = tweets.next() # Retrieve more tweets
        >>> for tweet in more_tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        """
        variables = {
            "count": count,
            "includePromotedContent": True,
            "latestControlAvailable": True,
            "requestContext": "launch",
            "withCommunity": True,
            "seenTweetIds": seen_tweet_ids or []
        }
        if cursor is not None:
            variables['cursor'] = cursor

        data = {
            'variables': variables,
            'queryId': get_query_id(Endpoint.HOME_TIMELINE),
            'features': FEATURES,
        }
        response = self.http.post(
            Endpoint.HOME_TIMELINE,
            data=json.dumps(data),
            headers=self._base_headers
        ).json()

        items = find_dict(response, 'entries')[0]
        next_cursor = items[-1]['content']['value']
        results = []

        for item in items:
            if 'itemContent' not in item['content']:
                continue
            tweet_info = find_dict(item, 'result')[0]
            if tweet_info['__typename'] == 'TweetWithVisibilityResults':
                tweet_info = tweet_info['tweet']
            user_info = tweet_info['core']['user_results']['result']
            results.append(Tweet(self, tweet_info, user_info))

        return Result(
            results,
            lambda:self.get_timeline(count, seen_tweet_ids, next_cursor),
            next_cursor
        )

    def favorite_tweet(self, tweet_id: str) -> Response:
        """
        Favorites a tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be liked.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.favorite_tweet(tweet_id)

        See Also
        --------
        .unfavorite_tweet
        """
        data = {
            'variables': {'tweet_id': tweet_id},
            'queryId': get_query_id(Endpoint.FAVORITE_TWEET)
        }
        response = self.http.post(
            Endpoint.FAVORITE_TWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def unfavorite_tweet(self, tweet_id: str) -> Response:
        """
        Unfavorites a tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be unliked.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.unfavorite_tweet(tweet_id)

        See Also
        --------
        .favorite_tweet
        """
        data = {
            'variables': {'tweet_id': tweet_id},
            'queryId': get_query_id(Endpoint.UNFAVORITE_TWEET)
        }
        response = self.http.post(
            Endpoint.UNFAVORITE_TWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def retweet(self, tweet_id: str) -> Response:
        """
        Retweets a tweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be retweeted.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.retweet(tweet_id)

        See Also
        --------
        .delete_retweet
        """
        data = {
            'variables': {'tweet_id': tweet_id, 'dark_request': False},
            'queryId': get_query_id(Endpoint.CREATE_RETWEET)
        }
        response = self.http.post(
            Endpoint.CREATE_RETWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def delete_retweet(self, tweet_id: str) -> Response:
        """
        Deletes the retweet.

        Parameters
        ----------
        tweet_id : str
            The ID of the retweeted tweet to be unretweeted.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.delete_retweet(tweet_id)

        See Also
        --------
        .retweet
        """
        data = {
            'variables': {'source_tweet_id': tweet_id,'dark_request': False},
            'queryId': get_query_id(Endpoint.DELETE_RETWEET)
        }
        response = self.http.post(
            Endpoint.DELETE_RETWEET,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def bookmark_tweet(self, tweet_id: str) -> Response:
        """
        Adds the tweet to bookmarks.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be bookmarked.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.bookmark_tweet(tweet_id)

        See Also
        --------
        .bookmark_tweet
        """

        data = {
            'variables': {'tweet_id': tweet_id},
            'queryId': get_query_id(Endpoint.CREATE_BOOKMARK)
        }
        response = self.http.post(
            Endpoint.CREATE_BOOKMARK,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def delete_bookmark(self, tweet_id: str) -> Response:
        """
        Removes the tweet from bookmarks.

        Parameters
        ----------
        tweet_id : str
            The ID of the tweet to be removed from bookmarks.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet_id = '...'
        >>> client.delete_bookmark(tweet_id)

        See Also
        --------
        .bookmark_tweet
        """
        data = {
            'variables': {'tweet_id': tweet_id},
            'queryId': get_query_id(Endpoint.DELETE_BOOKMARK)
        }
        response = self.http.post(
            Endpoint.DELETE_BOOKMARK,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def get_bookmarks(
        self, count: int = 20, cursor: str | None = None
    ) -> Result[Tweet]:
        """
        Retrieves bookmarks from the authenticated user's Twitter account.

        Parameters
        ----------
        count : int, default=20
            The number of bookmarks to retrieve (default is 20).
        cursor : str, default=None
            A cursor to paginate through the bookmarks (default is None).

        Returns
        -------
        Result[Tweet]
            A Result object containing a list of Tweet objects
            representing bookmarks.

        Example
        -------
        >>> bookmarks = client.get_bookmarks()
        >>> for bookmark in bookmarks:
        ...     print(bookmark)
        <Tweet id="...">
        <Tweet id="...">

        >>> more_bookmarks = bookmarks.next()  # To retrieve more bookmarks
        >>> for bookmark in more_bookmarks:
        ...     print(bookmark)
        <Tweet id="...">
        <Tweet id="...">
        """
        variables = {
            'count': count,
            'includePromotedContent': True
        }
        if cursor is not None:
            variables['cursor'] = cursor
        features = FEATURES | {
            'graphql_timeline_v2_bookmark_timeline': True
        }
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(features)
        }
        response = self.http.get(
            Endpoint.BOOKMARKS,
            params=params,
            headers=self._base_headers
        ).json()

        items_ = find_dict(response, 'entries')
        if not items_:
            return Result([])
        items = items_[0]
        next_cursor = items[-1]['content']['value']

        results = []
        for item in items:
            if not item['entryId'].startswith('tweet'):
                continue
            tweet_info = find_dict(item, 'tweet_results')[0]['result']
            user_info = tweet_info['core']['user_results']['result']
            results.append(Tweet(self, tweet_info, User(self, user_info)))

        return Result(
            results,
            lambda:self.get_bookmarks(count, next_cursor),
            next_cursor
        )

    def delete_all_bookmarks(self) -> Response:
        """
        Deleted all bookmarks.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> client.delete_all_bookmarks()
        """
        data = {
            'variables': {},
            'queryId': get_query_id(Endpoint.BOOKMARKS_ALL_DELETE)
        }
        response = self.http.post(
            Endpoint.BOOKMARKS_ALL_DELETE,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def follow_user(self, user_id: str) -> Response:
        """
        Follows a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to follow.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> user_id = '...'
        >>> client.follow_user(user_id)

        See Also
        --------
        .unfollow_user
        """
        data = urlencode({
            'include_profile_interstitial_type': 1,
            'include_blocking': 1,
            'include_blocked_by': 1,
            'include_followed_by': 1,
            'include_want_retweets': 1,
            'include_mute_edge': 1,
            'include_can_dm': 1,
            'include_can_media_tag': 1,
            'include_ext_is_blue_verified': 1,
            'include_ext_verified_type': 1,
            'include_ext_profile_image_shape': 1,
            'skip_status': 1,
            'user_id': user_id
        })
        headers = self._base_headers | {
            'content-type': 'application/x-www-form-urlencoded'
        }
        response = self.http.post(
            Endpoint.CREATE_FRIENDSHIPS,
            data=data,
            headers=headers
        )
        return response

    def unfollow_user(self, user_id: str) -> Response:
        """
        Unfollows a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to unfollow.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> user_id = '...'
        >>> client.unfollow_user(user_id)

        See Also
        --------
        .follow_user
        """
        data = urlencode({
            'include_profile_interstitial_type': 1,
            'include_blocking': 1,
            'include_blocked_by': 1,
            'include_followed_by': 1,
            'include_want_retweets': 1,
            'include_mute_edge': 1,
            'include_can_dm': 1,
            'include_can_media_tag': 1,
            'include_ext_is_blue_verified': 1,
            'include_ext_verified_type': 1,
            'include_ext_profile_image_shape': 1,
            'skip_status': 1,
            'user_id': user_id
        })
        headers = self._base_headers | {
            'content-type': 'application/x-www-form-urlencoded'
        }
        response = self.http.post(
            Endpoint.DESTROY_FRIENDSHIPS,
            data=data,
            headers=headers
        )
        return response

    def block_user(self, user_id: str) -> Response:
        """
        Blocks a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to block.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        .unblock_user
        """
        data = urlencode({'user_id': user_id})
        headers = self._base_headers
        headers['content-type'] = 'application/x-www-form-urlencoded'
        response = self.http.post(
            Endpoint.BLOCK_USER,
            data=data,
            headers=headers
        )
        return response

    def unblock_user(self, user_id: str) -> Response:
        """
        Unblocks a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to unblock.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        .block_user
        """
        data = urlencode({'user_id': user_id})
        headers = self._base_headers
        headers['content-type'] = 'application/x-www-form-urlencoded'
        response = self.http.post(
            Endpoint.UNBLOCK_USER,
            data=data,
            headers=headers
        )
        return response

    def mute_user(self, user_id: str) -> Response:
        """
        Mutes a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to mute.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        .unmute_user
        """
        data = urlencode({'user_id': user_id})
        headers = self._base_headers
        headers['content-type'] = 'application/x-www-form-urlencoded'
        response = self.http.post(
            Endpoint.MUTE_USER,
            data=data,
            headers=headers
        )
        return response

    def unmute_user(self, user_id: str) -> Response:
        """
        Unmutes a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to unmute.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        .mute_user
        """
        data = urlencode({'user_id': user_id})
        headers = self._base_headers
        headers['content-type'] = 'application/x-www-form-urlencoded'
        response = self.http.post(
            Endpoint.UNMUTE_USER,
            data=data,
            headers=headers
        )
        return response

    def get_trends(
        self,
        category: Literal[
            'trending', 'for-you', 'news', 'sports', 'entertainment'
        ],
        count: int = 20
    ) -> list[Trend]:
        """
        Retrieves trending topics on Twitter.

        Parameters
        ----------
        category : {'trending', 'for-you', 'news', 'sports', 'entertainment'}
            The category of trends to retrieve. Valid options include:
            - 'trending': General trending topics.
            - 'for-you': Trends personalized for the user.
            - 'news': News-related trends.
            - 'sports': Sports-related trends.
            - 'entertainment': Entertainment-related trends.
        count : int, default=20
            The number of trends to retrieve.

        Returns
        -------
        list[Trend]
            A list of Trend objects representing the retrieved trends.

        Examples
        --------
        >>> trends = client.get_trends('trending')
        >>> for trend in trends:
        ...     print(trend)
        <Trend name="...">
        <Trend name="...">
        ...
        """
        category = category.lower()
        if category in ['news', 'sports', 'entertainment']:
            category += '_unified'
        params = {
            'count': count,
            'include_page_configuration': True,
            'initial_tab_id': category
        }
        response = self.http.get(
            Endpoint.TREND,
            params=params,
            headers=self._base_headers
        ).json()

        entry_id_prefix = 'trends' if category == 'trending' else 'Guide'
        entries = [
            i for i in find_dict(response, 'entries')[0]
            if i['entryId'].startswith(entry_id_prefix)
        ]

        if not entries:
            # Recall the method again, as the trend information
            # may not be returned due to a Twitter error.
            return self.get_trends(category, count)

        items = entries[-1]['content']['timelineModule']['items']

        results = []
        for item in items:
            trend_info = item['item']['content']['trend']
            results.append(Trend(self, trend_info))

        return results

    def _get_user_friendship(
        self,
        user_id: str,
        count: int,
        endpoint: str
    ) -> list[User]:
        """
        Base function to get friendship.
        """
        params = {
            'variables': json.dumps({
                'userId': user_id,
                'count': count,
                'includePromotedContent': False
            }),
            'features': json.dumps(FEATURES)
        }
        response = self.http.get(
            endpoint,
            params=params,
            headers=self._base_headers
        ).json()

        items = find_dict(response, 'entries')[0]
        results = []
        for item in items:
            if not item['entryId'].startswith('user-'):
                continue
            user_info = find_dict(item, 'result')[0]
            results.append(User(self, user_info))
        return results

    def get_user_followers(self, user_id: str, count: int = 20) -> list[User]:
        """
        Retrieves a list of followers for a given user.

        Parameters
        ----------
        user_id : str
            The ID of the user for whom to retrieve followers.
        count : int, default=20
            The number of followers to retrieve.

        Returns
        -------
        list[User]
            A list of User objects representing the followers.
        """
        return self._get_user_friendship(
            user_id,
            count,
            Endpoint.FOLLOWERS
        )

    def get_user_verified_followers(
        self, user_id: str, count: int = 20
    ) -> list[User]:
        """
        Retrieves a list of verified followers for a given user.

        Parameters
        ----------
        user_id : str
            The ID of the user for whom to retrieve verified followers.
        count : int, default=20
            The number of verified followers to retrieve.

        Returns
        -------
        list[User]
            A list of User objects representing the verified followers.
        """
        return self._get_user_friendship(
            user_id,
            count,
            Endpoint.BLUE_VERIFIED_FOLLOWERS
        )

    def get_user_followers_you_know(
        self, user_id: str, count: int = 20
    ) -> list[User]:
        """
        Retrieves a list of common followers.

        Parameters
        ----------
        user_id : str
            The ID of the user for whom to retrieve followers you might know.
        count : int, default=20
            The number of followers you might know to retrieve.

        Returns
        -------
        list[User]
            A list of User objects representing the followers you might know.
        """
        return self._get_user_friendship(
            user_id,
            count,
            Endpoint.FOLLOWERS_YOU_KNOW
        )

    def get_user_following(self, user_id: str, count: int = 20) -> list[User]:
        """
        Retrieves a list of users whom the given user is following.

        Parameters
        ----------
        user_id : str
            The ID of the user for whom to retrieve the following users.
        count : int, default=20
            The number of following users to retrieve.

        Returns
        -------
        list[User]
            A list of User objects representing the users being followed.
        """
        return self._get_user_friendship(
            user_id,
            count,
            Endpoint.FOLLOWING
        )

    def get_user_subscriptions(
        self, user_id: str, count: int = 20
    ) -> list[User]:
        """
        Retrieves a list of users to which the specified user is subscribed.

        Parameters
        ----------
        user_id : str
            The ID of the user for whom to retrieve subscriptions.
        count : int, default=20
            The number of subscriptions to retrieve.

        Returns
        -------
        list[User]
            A list of User objects representing the subscribed users.
        """
        return self._get_user_friendship(
            user_id,
            count,
            Endpoint.SUBSCRIPTIONS
        )

    def _send_dm(
        self,
        conversation_id: str,
        text: str,
        media_id: str | None,
        reply_to: str | None
    ) -> dict:
        """
        Base function to send dm.
        """
        data = {
            'cards_platform': 'Web-12',
            'conversation_id': conversation_id,
            'dm_users': False,
            'include_cards': 1,
            'include_quote_count': True,
            'recipient_ids': False,
            'text': text
        }
        if media_id is not None:
            data['media_id'] = media_id
        if reply_to is not None:
            data['reply_to_dm_id'] = reply_to

        return self.http.post(
            Endpoint.SEND_DM,
            data=json.dumps(data),
            headers=self._base_headers
        ).json()

    def _get_dm_history(
        self,
        conversation_id: str,
        max_id: str | None = None
    ) -> dict:
        """
        Base function to get dm history.
        """
        params = {
            'context': 'FETCH_DM_CONVERSATION_HISTORY'
        }
        if max_id is not None:
            params['max_id'] = max_id

        return self.http.get(
            Endpoint.CONVERSASION.format(conversation_id),
            params=params,
            headers=self._base_headers
        ).json()

    def send_dm(
        self,
        user_id: str,
        text: str,
        media_id: str | None = None,
        reply_to: str | None = None
    ) -> Message:
        """
        Send a direct message to a user.

        Parameters
        ----------
        user_id : str
            The ID of the user to whom the direct message will be sent.
        text : str
            The text content of the direct message.
        media_id : str, default=None
            The media ID associated with any media content
            to be included in the message.
            Media ID can be received by using the :func:`.upload_media` method.
        reply_to : str, default=None
            Message ID to reply to.

        Returns
        -------
        Message
            `Message` object containing information about the message sent.

        Examples
        --------
        >>> # send DM with media
        >>> user_id = '000000000'
        >>> media_id = client.upload_media('image.png', 0)
        >>> message = client.send_dm(user_id, 'text', media_id)
        >>> print(message)
        <Message id='...'>

        See Also
        --------
        .upload_media
        .delete_dm
        """
        response = self._send_dm(
            f'{user_id}-{self.user_id()}', text, media_id, reply_to
        )

        message_data = find_dict(response, 'message_data')[0]
        users = list(response['users'].values())
        return Message(
            self,
            message_data,
            users[0]['id_str'],
            users[1]['id_str']
        )

    def add_reaction_to_message(
        self, message_id: str, conversation_id: str, emoji: str
    ) -> Response:
        """
        Adds a reaction emoji to a specific message in a conversation.

        Parameters
        ----------
        message_id : str
            The ID of the message to which the reaction emoji will be added.
            Group ID ('00000000') or partner_ID-your_ID ('00000000-00000001')
        conversation_id : str
            The ID of the conversation containing the message.
        emoji : str
            The emoji to be added as a reaction.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> message_id = '00000000'
        >>> conversation_id = f'00000001-{client.user_id()}'
        >>> client.add_reaction_to_message(
        ...    message_id, conversation_id, 'Emoji here'
        ... )
        """
        variables = {
            'messageId': message_id,
            'conversationId': conversation_id,
            'reactionTypes': ['Emoji'],
            'emojiReactions': [emoji]
        }
        data = {
            'variables': variables,
            'queryId': get_query_id(Endpoint.MESSAGE_ADD_REACTION)
        }
        response = self.http.post(
            Endpoint.MESSAGE_ADD_REACTION,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def remove_reaction_from_message(
        self, message_id: str, conversation_id: str, emoji: str
    ) -> Response:
        """
        Remove a reaction from a message.

        Parameters
        ----------
        message_id : str
            The ID of the message from which to remove the reaction.
        conversation_id : str
            The ID of the conversation where the message is located.
            Group ID ('00000000') or partner_ID-your_ID ('00000000-00000001')
        emoji : str
            The emoji to remove as a reaction.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> message_id = '00000000'
        >>> conversation_id = f'00000001-{client.user_id()}'
        >>> client.remove_reaction_from_message(
        ...    message_id, conversation_id, 'Emoji here'
        ... )
        """
        variables = {
            'conversationId': conversation_id,
            'messageId': message_id,
            'reactionTypes': ['Emoji'],
            'emojiReactions': [emoji]
        }
        data = {
            'variables': variables,
            'queryId': get_query_id(Endpoint.MESSAGE_REMOVE_REACTION)
        }
        response = self.http.post(
            Endpoint.MESSAGE_REMOVE_REACTION,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def delete_dm(self, message_id: str) -> Response:
        """
        Deletes a direct message with the specified message ID.

        Parameters
        ----------
        message_id : str
            The ID of the direct message to be deleted.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> client.delete_dm('0000000000')
        """

        data = {
            'variables': {
                'messageId': message_id
            },
            'queryId': get_query_id(Endpoint.DELETE_DM)
        }
        response = self.http.post(
            Endpoint.DELETE_DM,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def get_dm_history(
        self,
        user_id: str,
        max_id: str | None = None
    ) -> Result[Message]:
        """
        Retrieves the DM conversation history with a specific user.

        Parameters
        ----------
        user_id : str
            The ID of the user with whom the DM conversation
            history will be retrieved.
        max_id : str, default=None
            If specified, retrieves messages older than the specified max_id.

        Returns
        -------
        Result[Message]
            A Result object containing a list of Message objects representing
            the DM conversation history.

        Examples
        --------
        >>> messages = client.get_dm_history('0000000000')
        >>> for message in messages:
        >>>     print(message)
        <Message id="...">
        <Message id="...">
        ...
        ...

        >>> more_messages = messages.next()  # Retrieve more messages
        >>> for message in more_messages:
        >>>     print(message)
        <Message id="...">
        <Message id="...">
        ...
        ...
        """
        response = self._get_dm_history(f'{user_id}-{self.user_id()}', max_id)

        status = response['conversation_timeline']['status']
        if status == 'AT_END':
            # If there are no more messages, an empty result list is returned.
            return Result([])

        items = response['conversation_timeline']['entries']
        messages = []
        for item in items:
            message_info = item['message']['message_data']
            messages.append(Message(
                self,
                message_info,
                message_info['sender_id'],
                message_info['recipient_id']
            ))
        return Result(
            messages,
            lambda:self.get_dm_history(user_id, messages[-1].id)
        )

    def send_dm_to_group(
        self,
        group_id: str,
        text: str,
        media_id: str | None = None,
        reply_to: str | None = None
    ) -> GroupMessage:
        """
        Sends a message to a group.

        Parameters
        ----------
        group_id : str
            The ID of the group in which the direct message will be sent.
        text : str
            The text content of the direct message.
        media_id : str, default=None
            The media ID associated with any media content
            to be included in the message.
            Media ID can be received by using the :func:`.upload_media` method.
        reply_to : str, default=None
            Message ID to reply to.

        Returns
        -------
        GroupMessage
            `GroupMessage` object containing information about
            the message sent.

        Examples
        --------
        >>> # send DM with media
        >>> group_id = '000000000'
        >>> media_id = client.upload_media('image.png', 0)
        >>> message = client.send_dm_to_group(group_id, 'text', media_id)
        >>> print(message)
        <GroupMessage id='...'>

        See Also
        --------
        .upload_media
        .delete_dm
        """
        response = self._send_dm(
            group_id, text, media_id, reply_to
        )

        message_data = find_dict(response, 'message_data')[0]
        users = list(response['users'].values())
        return GroupMessage(
            self,
            message_data,
            users[0]['id_str'],
            group_id
        )

    def get_group_dm_history(
        self,
        group_id: str,
        max_id: str | None = None
    ) -> Result[GroupMessage]:
        """
        Retrieves the DM conversation history in a group.

        Parameters
        ----------
        group_id : str
            The ID of the group in which the DM conversation
            history will be retrieved.
        max_id : str, default=None
            If specified, retrieves messages older than the specified max_id.

        Returns
        -------
        Result[GroupMessage]
            A Result object containing a list of GroupMessage objects
            representing the DM conversation history.

        Examples
        --------
        >>> messages = client.get_group_dm_history('0000000000')
        >>> for message in messages:
        >>>     print(message)
        <GroupMessage id="...">
        <GroupMessage id="...">
        ...
        ...

        >>> more_messages = messages.next()  # Retrieve more messages
        >>> for message in more_messages:
        >>>     print(message)
        <GroupMessage id="...">
        <GroupMessage id="...">
        ...
        ...
        """
        response = self._get_dm_history(group_id, max_id)

        items = response['conversation_timeline']['entries']
        messages = []
        for item in items:
            if 'message' not in item:
                continue
            message_info = item['message']['message_data']
            messages.append(GroupMessage(
                self,
                message_info,
                message_info['sender_id'],
                group_id
            ))
        return Result(
            messages,
            lambda:self.get_group_dm_history(group_id, messages[-1].id)
        )

    def get_group(self, group_id: str) -> Group:
        """
        Fetches a guild by ID.

        Parameters
        ----------
        group_id : str
            The ID of the group to retrieve information for.

        Returns
        -------
        Group
            An object representing the retrieved group.
        """
        params = {
            'context': 'FETCH_DM_CONVERSATION_HISTORY',
            'include_conversation_info': True,
        }
        response = self.http.get(
            Endpoint.CONVERSASION.format(group_id),
            params=params,
            headers=self._base_headers
        ).json()
        return Group(self, group_id, response)

    def add_members_to_group(
        self, group_id: str, user_ids: list[str]
    ) -> Response:
        """Adds members to a group.

        Parameters
        ----------
        group_id : str
            ID of the group to which the member is to be added.
        user_ids : list[str]
            List of IDs of users to be added.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> group_id = '...'
        >>> members = ['...']
        >>> client.add_members_to_group(group_id, members)
        """
        data = {
            'variables': {
                'addedParticipants': user_ids,
                'conversationId': group_id
            },
            'queryId': get_query_id(Endpoint.ADD_MEMBER_TO_GROUP)
        }
        response = self.http.post(
            Endpoint.ADD_MEMBER_TO_GROUP,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def change_group_name(self, group_id: str, name: str) -> Response:
        """Changes group name

        Parameters
        ----------
        group_id : str
            ID of the group to be renamed.
        name : str
            New name.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.
        """
        data = urlencode({
            'name': name
        })
        headers = self._base_headers
        headers['content-type'] = 'application/x-www-form-urlencoded'
        response = self.http.post(
            Endpoint.CHANGE_GROUP_NAME.format(group_id),
            data=data,
            headers=headers
        )
        return response

    def create_list(
        self, name: str, description: str = '', is_private: bool = False
    ) -> List:
        """
        Creates a list.

        Parameters
        ----------
        name : str
            The name of the list.
        description : str, default=''
            The description of the list.
        is_private : bool, default=False
            Indicates whether the list is private (True) or public (False).

        Returns
        -------
        List
            The created list.

        Examples
        --------
        >>> list = client.create_list(
        ...     'list name',
        ...     'list description',
        ...     is_private=True
        ... )
        >>> print(list)
        <List id="...">
        """
        variables = {
            'isPrivate': is_private,
            'name': name,
            'description': description
        }
        data = {
            'variables': variables,
            'features': LIST_FEATURES,
            'queryId': get_query_id(Endpoint.CREATE_LIST)
        }
        response = self.http.post(
            Endpoint.CREATE_LIST,
            data=json.dumps(data),
            headers=self._base_headers
        ).json()
        list_info = find_dict(response, 'list')[0]
        return List(self, list_info)

    def edit_list_banner(self, list_id: str, media_id: str) -> Response:
        """
        Edit the banner image of a list.

        Parameters
        ----------
        list_id : str
            The ID of the list.
        media_id : str
            The ID of the media to use as the new banner image.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> list_id = '...'
        >>> media_id = client.upload_media('image.png', 0)
        >>> client.edit_list_banner(list_id, media_id)
        """
        variables = {
            'listId': list_id,
            'mediaId': media_id
        }
        data = {
            'variables': variables,
            'features': LIST_FEATURES,
            'queryId': get_query_id(Endpoint.EDIT_LIST_BANNER)
        }
        response = self.http.post(
            Endpoint.EDIT_LIST_BANNER,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def delete_list_banner(self, list_id: str) -> Response:
        """Deletes list banner.

        Parameters
        ----------
        list_id : str
            ID of the list from which the banner is to be removed.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.
        """
        data = {
            'variables': {
                'listId': list_id
            },
            'features': LIST_FEATURES,
            'queryId': get_query_id(Endpoint.DELETE_LIST_BANNER)
        }
        response = self.http.post(
            Endpoint.DELETE_LIST_BANNER,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def edit_list(
        self,
        list_id: str,
        name: str | None = None,
        description: str | None = None,
        is_private: bool | None = None
    ) -> List:
        """
        Edits list information.

        Parameters
        ----------
        list_id : str
            The ID of the list to edit.
        name : str, default=None
            The new name for the list.
        description : str, default=None
            The new description for the list.
        is_private : bool, default=None
            Indicates whether the list should be private
            (True) or public (False).

        Returns
        -------
        List
            The updated Twitter list.

        Examples
        --------
        >>> client.edit_list(
        ...     'new name', 'new description', True
        ... )
        """
        variables = {
            'listId': list_id
        }
        if name is not None:
            variables['name'] = name
        if description is not None:
            variables['description'] = description
        if is_private is not None:
            variables['isPrivate'] = is_private
        data = {
            'variables': variables,
            'features': LIST_FEATURES,
            'queryId': get_query_id(Endpoint.UPDATE_LIST)
        }
        response = self.http.post(
            Endpoint.UPDATE_LIST,
            data=json.dumps(data),
            headers=self._base_headers
        ).json()
        list_info = find_dict(response, 'list')[0]
        return List(self, list_info)

    def add_list_member(self, list_id: str, user_id: str) -> Response:
        """
        Adds a user to a list.

        Parameters
        ----------
        list_id : str
            The ID of the list.
        user_id : str
            The ID of the user to add to the list.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> client.add_list_member('list id', 'user id')
        """
        variables = {
            'listId': list_id,
            'userId': user_id
        }
        data = {
            'variables': variables,
            'features': LIST_FEATURES,
            'queryId': get_query_id(Endpoint.LIST_ADD_MEMBER)
        }
        response = self.http.post(
            Endpoint.LIST_ADD_MEMBER,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def remove_list_member(self, list_id: str, user_id: str) -> Response:
        """
        Removes a user from a list.

        Parameters
        ----------
        list_id : str
            The ID of the list.
        user_id : str
            The ID of the user to remove from the list.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> client.remove_list_member('list id', 'user id')
        """
        variables = {
            'listId': list_id,
            'userId': user_id
        }
        data = {
            'variables': variables,
            'features': LIST_FEATURES,
            'queryId': get_query_id(Endpoint.LIST_REMOVE_MEMBER)
        }
        response = self.http.post(
            Endpoint.LIST_REMOVE_MEMBER,
            data=json.dumps(data),
            headers=self._base_headers
        )
        return response

    def get_list(self, list_id: str) -> List:
        """
        Retrieve list by ID.

        Parameters
        ----------
        list_id : str
            The ID of the list to retrieve.

        Returns
        -------
        List
            List object.
        """
        params = {
            'variables': json.dumps({'listId': list_id}),
            'features': json.dumps(LIST_FEATURES)
        }
        response = self.http.get(
            Endpoint.LIST_BY_REST_ID,
            params=params,
            headers=self._base_headers
        ).json()
        list_info = find_dict(response, 'list')[0]
        return List(self, list_info)

    def get_list_tweets(
        self, list_id: str, count: int = 20, cursor: str | None = None
    ) -> Result[Tweet]:
        """
        Retrieves tweets from a list.

        Parameters
        ----------
        list_id : str
            The ID of the list to retrieve tweets from.
        count : int, default=20
            The number of tweets to retrieve.
        cursor : str, default=None
            The cursor for pagination.

        Returns
        -------
        Result[Tweet]
            A Result object containing the retrieved tweets.

        Examples
        --------
        >>> tweets = client.get_list_tweets('list id')
        >>> for tweet in tweets:
        ...    print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...

        >>> more_tweets = tweets.next()  # Retrieve more tweets
        >>> for tweet in more_tweets:
        ...     print(tweet)
        <Tweet id="...">
        <Tweet id="...">
        ...
        ...
        """
        variables = {
            'listId': list_id,
            'count': count
        }
        if cursor is not None:
            variables['cursor'] = cursor
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(FEATURES)
        }
        response = self.http.get(
            Endpoint.LIST_LATEST_TWEETS,
            params=params,
            headers=self._base_headers
        ).json()

        items = find_dict(response, 'entries')[0]
        next_cursor = items[-1]['content']['value']

        results = []
        for item in items:
            if not item['entryId'].startswith('tweet'):
                continue
            tweet_info = find_dict(item, 'result')[0]
            if tweet_info['__typename'] == 'TweetWithVisibilityResults':
                tweet_info = tweet_info['tweet']
            user_info = find_dict(tweet_info, 'result')[0]
            results.append(Tweet(self, tweet_info, User(self, user_info)))

        return Result(
            results,
            lambda: self.get_list_tweets(list_id, count, next_cursor),
            next_cursor
        )
