from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from httpx import Response

    from .client import Client
    from .user import Result, User


class Tweet:
    """
    Attributes
    ----------
    id : str
        The unique identifier of the tweet.
    created_at : str
        The date and time when the tweet was created.
    user: User
        Author of the tweet.
    text : str
        The full text of the tweet.
    lang : str
        The language of the tweet.
    is_quote_status : bool
        Indicates if the tweet is a quote status.
    possibly_sensitive : bool
        Indicates if the tweet content may be sensitive.
    possibly_sensitive_editable : bool
        Indicates if the tweet's sensitivity can be edited.
    quote_count : int
        The count of quotes for the tweet.
    media : list
        A list of media entities associated with the tweet.
    reply_count : int
        The count of replies to the tweet.
    favorite_count : int
        The count of favorites or likes for the tweet.
    favorited : bool
        Indicates if the tweet is favorited.
    view_count: int
        The count of views.
    retweet_count : int
        The count of retweets for the tweet.
    editable_until_msecs : int
        The timestamp until which the tweet is editable.
    is_translatable : bool
        Indicates if the tweet is translatable.
    is_edit_eligible : bool
        Indicates if the tweet is eligible for editing.
    edits_remaining : int
        The remaining number of edits allowed for the tweet.
    state : str
        The state of the tweet views.
    replies: Result[Tweet] | None
        Replies to the tweet.
    reply_to: list[Tweet] | None
        A list of Tweet objects representing the tweets to which to reply.
    """

    def __init__(self, client: Client, data: dict, user: User = None) -> None:
        self._client = client
        self._data = data
        self.user = user

        self.replies: Result[Tweet] | None = None
        self.reply_to: list[Tweet] | None = None

        self.id: str = data['rest_id']

        legacy = data['legacy']
        self.created_at: str = legacy['created_at']
        self.text: str = legacy['full_text']
        self.lang: str = legacy['lang']
        self.is_quote_status: bool = legacy['is_quote_status']
        self.possibly_sensitive: bool = legacy.get('possibly_sensitive')
        self.possibly_sensitive_editable: bool = legacy.get(
            'possibly_sensitive_editable')
        self.quote_count: int = legacy['quote_count']
        self.media: list = legacy['entities'].get('media')
        self.reply_count: int = legacy['reply_count']
        self.favorite_count: int = legacy['favorite_count']
        self.favorited: bool = legacy['favorited']
        self.view_count: int = data['views'].get('count')
        self.retweet_count: int = legacy['retweet_count']
        self.editable_until_msecs: int = data['edit_control'].get(
            'editable_until_msecs')
        self.is_translatable: bool = data['is_translatable']
        self.is_edit_eligible: bool = data['edit_control'].get(
            'is_edit_eligible')
        self.edits_remaining: int = data['edit_control'].get('edits_remaining')
        self.state: str = data['views']['state']

    def delete(self) -> Response:
        """Deletes the tweet.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        Examples
        --------
        >>> tweet.delete()
        """
        return self._client.delete_tweet(self.id)

    def favorite(self) -> Response:
        """
        Favorites the tweet.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        Client.favorite_tweet
        """
        return self._client.favorite_tweet(self.id)

    def unfavorite(self) -> Response:
        """
        Favorites the tweet.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        Client.unfavorite_tweet
        """
        return self._client.unfavorite_tweet(self.id)

    def retweet(self) -> Response:
        """
        Retweets the tweet.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        Client.retweet
        """
        return self._client.retweet(self.id)

    def delete_retweet(self) -> Response:
        """
        Deletes the retweet.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        Client.delete_retweet
        """
        return self._client.delete_retweet(self.id)

    def bookmark(self) -> Response:
        """
        Adds the tweet to bookmarks.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        Client.bookmark_tweet
        """
        return self._client.bookmark_tweet(self.id)

    def delete_bookmark(self) -> Response:
        """
        Removes the tweet from bookmarks.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.

        See Also
        --------
        Client.delete_bookmark
        """
        return self._client.delete_bookmark(self.id)

    def reply(
        self,
        text: str = '',
        media_ids: list[str] | None = None
    ) -> Tweet:
        """
        Replies to the tweet.

        Parameters
        ----------
        text : str, default=''
            The text content of the reply.
        media_ids : list[str], default=None
            A list of media IDs or URIs to attach to the reply.
            Media IDs can be obtained by using the `upload_media` method.

        Returns
        -------
        Tweet
            The created tweet.

        Examples
        --------
        >>> tweet_text = 'Example text'
        >>> media_ids = [
        ...     client.upload_media('image1.png', 0),
        ...     client.upload_media('image1.png', 1)
        ... ]
        >>> tweet.reply(
        ...     tweet_text,
        ...     media_ids=media_ids
        ... )

        See Also
        --------
        `Client.upload_media`
        """
        return self._client.create_tweet(text, media_ids, reply_to=self.id)

    def get_retweeters(
        self, count: str = 40, cursor: str | None = None
    ) -> Result[User]:
        """
        Retrieve users who retweeted the tweet.

        Parameters
        ----------
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
        >>> retweeters = tweet.get_retweeters()
        >>> print(retweeters)
        [<User id="...">, <User id="...">, ..., <User id="...">]

        >>> more_retweeters = retweeters.next()  # Retrieve more retweeters.
        >>> print(more_retweeters)
        [<User id="...">, <User id="...">, ..., <User id="...">]
        """
        return self._client.get_retweeters(self.id, count, cursor)

    def get_favoriters(
        self, count: str = 40, cursor: str | None = None
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
        >>> favoriters = tweet.get_favoriters()
        >>> print(favoriters)
        [<User id="...">, <User id="...">, ..., <User id="...">]

        >>> more_favoriters = favoriters.next()  # Retrieve more favoriters.
        >>> print(more_favoriters)
        [<User id="...">, <User id="...">, ..., <User id="...">]
        """
        return self._client.get_favoriters(self.id, count, cursor)

    def __repr__(self) -> str:
        return f'<Tweet id="{self.id}">'

    def __eq__(self, __value: object) -> bool:
        return isinstance(__value, Tweet) and self.id == __value.id

    def __ne__(self, __value: object) -> bool:
        return not self == __value


class ScheduledTweet:
    def __init__(self, client: Client, data: dict) -> None:
        self._client = client

        self.id = data['rest_id']
        self.execute_at: int = data['scheduling_info']['execute_at']
        self.state: str = data['scheduling_info']['state']
        self.type: str = data['tweet_create_request']['type']
        self.text: str = data['tweet_create_request']['status']
        self.media = [i['media_info'] for i in data.get('media_entities', [])]

    def delete(self) -> Response:
        """
        Delete the scheduled tweet.

        Returns
        -------
        httpx.Response
            Response returned from twitter api.
        """
        return self._client.delete_scheduled_tweet(self.id)

    def __repr__(self) -> str:
        return f'<ScheduledTweet id="{self.id}">'
