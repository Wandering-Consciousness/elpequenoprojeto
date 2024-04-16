# coding: utf-8

import logging
import json
import os
import time
from urllib.parse import quote

from django.utils import timezone

from woid.apps.services import wrappers
from woid.apps.services.models import Service, Story, StoryUpdate

logger = logging.getLogger(__name__)

call_counter = 0

def udio_it(prompt, url):
    global call_counter
    prompt = prompt.replace("'", "").replace('"', '')
    udio_curl = "curl -H 'accept: application/json, text/plain, */*' -H 'content-type: application/json' -H 'origin: https://www.udio.com' -H 'cookie: _ga_RF4WWQM7BF=GS1.1.1713208564.1.1.1713209172.0.0.0' -H 'cookie: _ga=GA1.1.94385292.1713208564' -H 'cookie: sb-api-auth-token=***INSERT YOUR OWN SB-API-AUTH-TOKEN FROM YOUR BROWSER COOKIES WITH Udio.com***' -H 'user-agent: https://www.reddit.com/r/elpequenoprojeto/ The Little Project' -H 'referer: https://www.udio.com/search' --compressed -X POST https://www.udio.com/api/generate-proxy -d '{\"prompt\":\"" + prompt + "\",\"samplerOptions\":{\"seed\":-1,\"bypass_prompt_optimization\":false}}'"
    print("Udio it! PROMPT: ", prompt, " >>> URL: ", url)
    call_counter += 1
    cmd_out = os.popen(udio_curl).read()
    if "Success" in cmd_out:
        response_j = json.loads(cmd_out)
        track_ids = response_j['track_ids']
        print("track 1 ID: ", track_ids[0], "track 2 ID: ", track_ids[1])

        # Post to Reddit
        title = quote(prompt)
        text = "Generated [this song](https://www.udio.com/songs/" + track_ids[0] + ") and [this song](https://www.udio.com/songs/" + track_ids[1] + ") based on [this news](" + url + ")"
        reddit_curl = 'curl -i -H "Authorization: Bearer ***INSERT YOUR REDDIT ACCESS TOKEN***" -H "User-Agent: https://www.reddit.com/r/elpequenoprojeto/ The Little Project" -H "Content-Type: application/x-www-form-urlencoded" -X POST -d "title=' + title + '&kind=self&sr=elpequenoprojeto&resubmit=true&sendreplies=true&text=' + text + '" https://oauth.reddit.com/api/submit'
        cmd_out = os.popen(reddit_curl).read()
    else:
        print("Call failed")

    if call_counter == 2:
        print("Sleeping...")
        time.sleep(90)
        call_counter = 0
        print("Awake")
        print("")

class AbstractBaseCrawler:
    def __init__(self, slug, client):
        self.service = Service.objects.get(slug=slug)
        self.slug = slug
        self.client = client

    def run(self):
        try:
            self.service.status = Service.CRAWLING
            self.service.last_run = timezone.now()
            self.service.save()
            self.update_top_stories()
            self.service.status = Service.GOOD
            self.service.save()
        except Exception:
            self.service.status = Service.ERROR
            self.service.save()


class HackerNewsCrawler(AbstractBaseCrawler):
    def __init__(self):
        super().__init__('hn', wrappers.HackerNewsClient())

    def update_top_stories(self):
        try:
            stories = self.client.get_top_stories()
            i = 1
            for code in stories:
                self.update_story(code)
                i += 1
                if i > 100:
                    break
        except Exception:
            logger.exception('An error occurred while executing `update_top_stores` for Hacker News.')
            raise

    def update_story(self, code):
        try:
            story_data = self.client.get_story(code)
            if story_data and story_data['type'] == 'story':
                story, created = Story.objects.get_or_create(service=self.service, code=code)

                if story_data.get('deleted', False):
                    story.delete()
                    return

                if story.status == Story.NEW:
                    story.date = timezone.datetime.fromtimestamp(
                        story_data.get('time'),
                        timezone.get_current_timezone()
                    )
                    story.url = u'{0}{1}'.format(story.service.story_url, story.code)

                score = story_data.get('score', 0)
                comments = story_data.get('descendants', 0)

                # has_changes = (score != story.score or comments != story.comments)

                # if not story.status == Story.NEW and has_changes:
                #     update = StoryUpdate(story=story)
                #     update.comments_changes = comments - story.comments
                #     update.score_changes = score - story.score
                #     update.save()

                story.comments = comments
                story.score = score
                story.title = story_data.get('title', '')

                url = story_data.get('url', '')
                if url:
                    story.content_type = Story.URL
                    story.content = url

                text = story_data.get('text', '')
                if text:
                    story.content_type = Story.TEXT
                    story.content = text

                is_new = False
                if story.status == Story.NEW:
                    is_new = True

                story.status = Story.OK
                story.save()

                if is_new:
                    if url:
                        udio_it(story.title, url)
                    elif story.content_type == Story.TEXT:
                        udio_it(story.title + " " + text, story.url)

        except Exception:
            logger.exception('Exception in code {0} HackerNewsCrawler.update_story'.format(code))


class RedditCrawler(AbstractBaseCrawler):
    def __init__(self):
        super().__init__('reddit', wrappers.RedditClient())

    def update_top_stories(self):
        try:
            stories = self.client.get_front_page_stories()
            for data in stories:
                story_data = data['data']
                story, created = Story.objects.get_or_create(service=self.service, code=story_data.get('permalink'))
                if created:
                    story.date = timezone.datetime.fromtimestamp(
                        story_data.get('created_utc'),
                        timezone.get_current_timezone()
                    )
                    story.build_url()

                score = story_data.get('score', 0)
                comments = story_data.get('num_comments', 0)

                # has_changes = (score != story.score or comments != story.comments)

                # if not story.status == Story.NEW and has_changes:
                #     update = StoryUpdate(story=story)
                #     update.comments_changes = comments - story.comments
                #     update.score_changes = score - story.score
                #     update.save()

                story.comments = comments
                story.score = score
                story.title = story_data.get('title', '')
                story.nsfw = story_data.get('over_18', False)

                is_new = False
                if story.status == Story.NEW:
                    is_new = True

                story.status = Story.OK
                story.save()

                if is_new:
                    udio_it(story.title, story.url)

        except Exception:
            logger.exception('An error occurred while executing `update_top_stores` for Reddit.')
            raise


class GithubCrawler(AbstractBaseCrawler):
    def __init__(self):
        super().__init__('github', wrappers.GithubClient())

    def update_top_stories(self):
        try:
            repos = self.client.get_today_trending_repositories()
            today = timezone.now()
            for data in repos:
                story, created = Story.objects.get_or_create(
                    service=self.service,
                    code=data.get('name'),
                    date=timezone.datetime(today.year, today.month, today.day, tzinfo=timezone.get_current_timezone())
                )
                if created:
                    story.build_url()

                stars = data.get('stars', 0)

                # Because of the nature of the github trending repositories
                # we are only interested on changes where the stars have increased
                # this way the crawler is gonna campure the highest starts one repository
                # got in a single day
                has_changes = (stars > story.score)

                if story.status == Story.NEW:
                    story.score = stars
                elif has_changes:
                    # update = StoryUpdate(story=story)
                    # update.score_changes = stars - story.score
                    # update.save()
                    story.score = stars

                story.title = data.get('name')[1:]

                description = data.get('description', '')
                language = data.get('language', '')

                if language and description:
                    description = '{0} • {1}'.format(language, description)
                elif language:
                    description = language

                story.description = description

                # TODO: Check if this Crawler is actually getting any data
                is_new = False
                if story.status == Story.NEW:
                    is_new = True

                story.status = Story.OK
                story.save()

                if is_new:
                    udio_it(story.title + " " + story.description, story.url)

        except Exception:
            logger.exception('An error occurred while executing `update_top_stores` for GitHub.')
            raise


class NYTimesCrawler(AbstractBaseCrawler):
    def __init__(self):
        super().__init__('nytimes', wrappers.NYTimesClient())

    def save_story(self, story_data, score, weight):
        story_id = story_data.get('id', story_data.get('asset_id', None))
        if not story_id:
            return

        today = timezone.now()
        story, created = Story.objects.get_or_create(
                service=self.service,
                code=story_id,
                date=timezone.datetime(today.year, today.month, today.day, tzinfo=timezone.get_current_timezone())
            )

        story.title = story_data['title']
        story.url = story_data['url']

        minutes_since_last_update = 0

        if story.updates.exists():
            last_update = story.updates.order_by('-updated_at').first()
            delta = timezone.now() - last_update.updated_at
            minutes_since_last_update = delta.total_seconds() / 60

        if created or minutes_since_last_update >= 30:
            score_run = score * weight
            story.score += score_run

            update = StoryUpdate(story=story)
            update.score_changes = score_run
            update.save()

        is_new = False
        if story.status == Story.NEW:
            is_new = True

        story.status = Story.OK
        story.save()

        if is_new:
            udio_it(story.title, story.url)

    def update_top_stories(self):
        try:
            popular_stories = self.client.get_most_popular_stories()

            score = 20
            for story_data in popular_stories['mostviewed']:
                self.save_story(story_data, score, 4)
                score -= 1

            score = 20
            for story_data in popular_stories['mostshared']:
                self.save_story(story_data, score, 2)
                score -= 1

            score = 20
            for story_data in popular_stories['mostemailed']:
                self.save_story(story_data, score, 1)
                score -= 1

        except Exception:
            logger.exception('An error occurred while executing `update_top_stores` for NYTimes.')
            raise


class ProductHuntCrawler(AbstractBaseCrawler):
    def __init__(self):
        super().__init__('producthunt', wrappers.ProductHuntClient())

    def update_top_stories(self):
        try:
            posts = self.client.get_top_posts()
            today = timezone.now()
            for post in posts:
                code = post['slug']
                story, created = Story.objects.get_or_create(
                    service=self.service,
                    code=code,
                    date=timezone.datetime(today.year, today.month, today.day, tzinfo=timezone.get_current_timezone())
                )

                if created:
                    story.title = post['name']
                    story.description = post['tagline']
                    story.url = u'{0}{1}'.format(self.service.story_url, code)

                story.score = post['votes_count']
                story.comments = post['comments_count']
                story.status = Story.OK
                story.save()

        except Exception:
            logger.exception('An error occurred while executing `update_top_stores` for Product Hunt.')
            raise
