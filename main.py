import json
import random
import time
import os
from dotenv import load_dotenv

from twikit.client import Client
from twikit.tweet import Tweet

load_dotenv()

authFilePath = './dump/auth.json'
followingsFilePath = './dump/followings.json'

USERNAME = os.getenv('TWITTER_USERNAME')
EMAIL = os.getenv('TWITTER_EMAIL')
PASSWORD = os.getenv('TWITTER_PASSWORD')
id = input("Please enter tweet id: ")

# Initialize client
client = Client('en-US')

def auth():
    if os.path.exists(authFilePath):
        client.load_cookies(authFilePath)
        print('Loaded cookies from file')
    else:
        client.login(
            auth_info_1=USERNAME ,
            auth_info_2=EMAIL,
            password=PASSWORD
        )
        client.save_cookies('./dump/auth.json')

def get_tweet_details_by_id(id):
    tweet = client.get_tweet_by_id(id)
    print(f'Getting tweet details for tweet id: {id}')
    print(f'Username: {tweet.user.screen_name}')
    print(f'Like count: {tweet.favorite_count}')
    print(f'Retweet count: {tweet.retweet_count}')
    print(f'Mention count: {tweet.reply_count}')
    return tweet

def get_my_followings():
    list = []
    try:
        if os.path.exists(followingsFilePath):
            with open(followingsFilePath, 'r') as file:
                list = json.load(file)
        else:
            followings = client.get_user_following(client.user_id(),count=200000)
            for following in followings:
                list.append({
                    'username': following.screen_name,
                    'id': following.id
                })
            with open(followingsFilePath, 'w') as file:
                json.dump(list, file, indent=4)
    except Exception as e:
        return list
    
    return list

def get_retweeters(id):
    list = []
    try:
        retweeters = client.get_retweeters(id)
        while True:
            if len(retweeters) == 0:
                break
            for retweeter in retweeters:
                list.append({
                    'username': retweeter.screen_name,
                    'id': retweeter.id
                })
            retweeters = retweeters.next()
            wait_time = random.uniform(1, 3)
            time.sleep(wait_time)
    except Exception as e:
        return list
    return list

def get_favoriters(id):
    list = []
    try:
        favoriters = client.get_favoriters(id)
        while True:
            if len(favoriters) == 0:
                break
            for favoriter in favoriters:
                list.append({
                    'username': favoriter.screen_name,
                    'id': favoriter.id
                })
            favoriters = favoriters.next()
            wait_time = random.uniform(1, 3)
            time.sleep(wait_time)
    except Exception as e:
        return list
    return list

def get_mentions(tweet: Tweet):
    list = []
    try:
        replies = []
        if len(tweet.replies) == 0:
            replies = tweet.replies.next()
        while True:
            if len(replies) == 0:
                break
            for reply in replies:
                list.append({
                    'username': reply.user.screen_name,
                    'id': reply.id
                })
            replies = replies.next()
    except Exception as e:
        return list
    return list

auth()
print(f'Logged in as {client.user().id}')
print(f'Username: {client.user().screen_name}')

followingMap = dict()
followings = get_my_followings()
print(f'Followings count: {len(followings)}')
for following in followings:
    followingMap[following['id']] = following['username']

tweet = get_tweet_details_by_id(id)

print(f'Getting all related users about tweet id: {id}')

print('Getting retweeters...')
retweeters = get_retweeters(id)
print(f'Retweeters count: {len(retweeters)}')

print('Getting favoriters...')
favoriters = get_favoriters(id)
print(f'Likers count: {len(favoriters)}')

print('Getting mentioners...')
mentions = get_mentions(tweet)
print(f'Mentioners count: {len(mentions)}')

print('Blocking all users...')
for retweeter in retweeters:
    if retweeter['id'] in followingMap:
        print(f'User {retweeter["username"]} is following you, skipping...')
        continue
    client.block_user(retweeter['id'])
    wait_time = random.uniform(1, 3)
    time.sleep(wait_time)
    
for favoriter in favoriters:
    if favoriter['id'] in followingMap:
        print(f'User {favoriter["username"]} is following you, skipping...')
        continue
    client.block_user(favoriter['id'])
    wait_time = random.uniform(1, 3)
    time.sleep(wait_time)
    
for mention in mentions:
    if mention['id'] in followingMap:
        print(f'User {mention["username"]} is following you, skipping...')
        continue
    client.block_user(mention['id'])
    wait_time = random.uniform(1, 3)
    time.sleep(wait_time)