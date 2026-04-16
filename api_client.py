"""
api_client.py — JSONPlaceholder API client.

Fetches blog posts from https://jsonplaceholder.typicode.com/posts
and formats them for writing to Notepad.

Falls back to bundled sample posts if the API is unreachable.
"""

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

POSTS_URL = "https://jsonplaceholder.typicode.com/posts"
REQUEST_TIMEOUT = 15.0  # seconds

# Bundled fallback posts — used when the API is unreachable.
# These mirror the exact format returned by JSONPlaceholder.
_FALLBACK_POSTS = [
    {"id": 1, "userId": 1, "title": "sunt aut facere repellat provident occaecati excepturi optio reprehenderit", "body": "quia et suscipit\nsuscipit recusandae consequuntur expedita et cum\nreprehenderit molestiae ut ut quas totam\nnostrum rerum est autem sunt rem eveniet architecto"},
    {"id": 2, "userId": 1, "title": "qui est esse", "body": "est rerum tempore vitae\nsequi sint nihil reprehenderit dolor beatae ea dolores neque\nfugiat blanditiis voluptate porro vel nihil molestiae ut reiciendis\nqui aperiam non debitis possimus qui neque nisi nulla"},
    {"id": 3, "userId": 1, "title": "ea molestias quasi exercitationem repellat qui ipsa sit aut", "body": "et iusto sed quo iure\nvoluptatem occaecati omnis eligendi aut ad\nvoluptatem doloribus vel accusantium quis pariatur\nmolestiae porro eius odio et labore et velit aut"},
    {"id": 4, "userId": 1, "title": "eum et est occaecati", "body": "ullam et saepe reiciendis voluptatem adipisci\nsit amet autem assumenda provident rerum culpa\nquis hic commodi nesciunt rem tenetur doloremque ipsam iure\nquis sunt voluptatem rerum illo velit"},
    {"id": 5, "userId": 1, "title": "nesciunt quas odio", "body": "repudiandae veniam quaerat sunt sed\nalias aut fugiat sit autem sed est\nvoluptatem omnis possimus esse voluptatibus quis\nest aut tenetur dolor neque"},
    {"id": 6, "userId": 1, "title": "dolorem eum magni eos aperiam quia", "body": "ut aspernatur corporis harum nihil quis provident sequi\nmollitia nobis aliquid molestiae\nperspiciatis et ea nemo ab reprehenderit accusantium quas\nvoluptatem exercitationem"},
    {"id": 7, "userId": 1, "title": "magnam facilis autem", "body": "dolore placeat quibusdam ea quo vitae\nmagni quis enim qui quis quo nemo aut saepe\nquidem repellat excepturi ut quia\nsunt ut sequi eos ea sed quas"},
    {"id": 8, "userId": 1, "title": "dolorem dolore est ipsam", "body": "dignissimos aperiam dolorem qui eum\nfacilis quibusdam animi sint suscipit qui sint possimus cum\nquaerat magni maiores excepturi\nipsam ut commodi dolor voluptatum modi aut vitae"},
    {"id": 9, "userId": 1, "title": "nesciunt iure omnis dolorem tempora et accusantium", "body": "consectetur animi nesciunt iure dolore\nenim quia ad\nveniam autem ut quam aut nobis\net est aut quod aut provident voluptas autem voluptas"},
    {"id": 10, "userId": 1, "title": "optio molestias id quia eum", "body": "quo et expedita modi cum officia vel magni\ndoloribus qui repudiandae\nvero nisi sit\nquos veniam quod sed accusamus veritatis error"},
]


@dataclass
class Post:
    id: int
    title: str
    body: str
    user_id: int

    def format_content(self) -> str:
        """Format the post for writing into a Notepad file."""
        return f"Title: {self.title}\n\n{self.body}"

    @property
    def filename(self) -> str:
        return f"post_{self.id}.txt"


def fetch_posts(limit: int = 10) -> list[Post]:
    """
    Fetch the first `limit` blog posts from JSONPlaceholder.

    Falls back to bundled sample posts if the API is unreachable,
    so the automation always has data to work with.

    Args:
        limit: Maximum number of posts to return (default 10).

    Returns:
        List of Post objects, length <= limit.
    """
    log.info("Fetching up to %d posts from %s", limit, POSTS_URL)
    data = None

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.get(POSTS_URL)
            response.raise_for_status()
        data = response.json()
        log.info("API reachable — using live data")
    except httpx.TimeoutException:
        log.warning("Request timed out — falling back to bundled posts")
    except httpx.RequestError as exc:
        log.warning("Network error (%s) — falling back to bundled posts", exc)
    except httpx.HTTPStatusError as exc:
        log.warning("HTTP %d from API — falling back to bundled posts", exc.response.status_code)
    except Exception as exc:
        log.warning("Unexpected error fetching posts (%s) — falling back to bundled posts", exc)

    if data is None:
        data = _FALLBACK_POSTS

    posts = []
    for item in data[:limit]:
        try:
            posts.append(Post(
                id=item["id"],
                title=item["title"],
                body=item["body"],
                user_id=item["userId"],
            ))
        except KeyError as exc:
            log.warning("Skipping malformed post entry (missing field %s): %s", exc, item)

    log.info("Using %d posts (source: %s)", len(posts), "API" if data is not _FALLBACK_POSTS else "fallback")
    return posts
