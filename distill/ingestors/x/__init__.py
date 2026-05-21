"""X (Twitter) ingestor.

Uses the public ``cdn.syndication.twimg.com`` embed endpoint that publishers
use to render tweet embeds on third-party sites. This is the sanctioned
public path, not an anti-bot workaround — distillr's roadmap explicitly
excludes login-walled scraping.
"""

from distill.ingestors.x.syndication import (
    TweetRecord,
    fetch_tweet,
    parse_tweet_url,
)

__all__ = ["TweetRecord", "fetch_tweet", "parse_tweet_url"]
