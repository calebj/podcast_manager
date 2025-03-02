"""Tests for the URL cleaner in the episode downloader."""

import unittest

from podcast_manager.downloaders.episode import EpisodeDownloader


class TestUrlCleaner(unittest.TestCase):
    """Test the URL cleaner functionality."""

    def setUp(self):
        """Set up the test environment."""
        # We only need the _clean_episode_url method, so we can pass None for session
        self.downloader = EpisodeDownloader("downloads")

    def test_clean_tracking_redirects(self):
        """Test cleaning URLs with tracking redirects."""
        # Example from the description
        complex_url = "https://podtrac.com/pts/redirect.mp3/arttrk.com/p/ABCDEF/pdst.fm/e/69/claritaspod.com/measure/traffic.omny.fm/d/clips/asdfasdf/audio.mp3?utm_source=Podcast&in_playlist=961e484b-1dff-48ef-8bdd-ae2b00350fab"
        expected = "https://traffic.omny.fm/d/clips/asdfasdf/audio.mp3"

        clean_url = self.downloader._clean_episode_url(complex_url)
        self.assertEqual(clean_url, expected)

    def test_clean_simple_url(self):
        """Test that simple URLs without tracking are left mostly intact."""
        simple_url = "https://www.example.com/podcast/episode1.mp3"
        clean_url = self.downloader._clean_episode_url(simple_url)
        self.assertEqual(clean_url, simple_url)

    def test_preserve_essential_params(self):
        """Test that essential parameters are preserved."""
        url_with_params = "https://example.com/podcast/episode1.mp3?token=abc123&expires=1234567890&utm_source=twitter"
        expected = "https://example.com/podcast/episode1.mp3?expires=1234567890&token=abc123"

        clean_url = self.downloader._clean_episode_url(url_with_params)
        # We need to handle the order of parameters which may not be consistent
        self.assertEqual(
            set(clean_url.split('?')[1].split('&')),
            set(expected.split('?')[1].split('&')),
        )

    def test_multiple_domains_in_path(self):
        """Test URLs with multiple domains in the path."""
        url = "https://redirect.example.com/redirect/media.podcasthost.com/shows/episode.mp3"
        expected = "https://media.podcasthost.com/shows/episode.mp3"

        clean_url = self.downloader._clean_episode_url(url)
        self.assertEqual(clean_url, expected)

    def test_encoded_url_path_segment(self):
        """Test URLs with an encoded URL as a path segment."""
        url = "https://example.com/redirect/https%3A%2F%2Fmedia.example.org%2Fepisode123.mp3"
        expected = "https://media.example.org/episode123.mp3"

        clean_url = self.downloader._clean_episode_url(url)
        self.assertEqual(clean_url, expected)


if __name__ == "__main__":
    unittest.main()
