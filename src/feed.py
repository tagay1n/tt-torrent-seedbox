import feedparser
from config import load_config

def run(config_path):
    config = load_config(config_path)
    feed = feedparser.parse(config.tracker.feed_url)
    
    
