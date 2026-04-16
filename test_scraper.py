"""
Suite de tests pour le scraper Instagram.

Tests unitaires et intégration pour vérifier que le scraper fonctionne.
"""

import pytest
from exceptions import ValidationError
from validators import validate_instagram_url, validate_post_count


class TestValidators:
    """Tests des validators."""

    def test_valid_instagram_url(self):
        """URL Instagram valide."""
        url = validate_instagram_url("https://www.instagram.com/instagram")
        assert url == "https://www.instagram.com/instagram"

    def test_instagram_url_without_www(self):
        """URL Instagram sans www devrait être normalisée."""
        url = validate_instagram_url("https://instagram.com/instagram")
        assert url == "https://www.instagram.com/instagram"

    def test_invalid_domain_raises(self):
        """URL d'un autre domaine devrait lever ValidationError."""
        with pytest.raises(ValidationError):
            validate_instagram_url("https://facebook.com/instagram")

    def test_instagram_url_without_username_raises(self):
        """URL sans nom d'utilisateur devrait lever ValidationError."""
        with pytest.raises(ValidationError):
            validate_instagram_url("https://www.instagram.com/")

    def test_empty_url_raises(self):
        """URL vide devrait lever ValidationError."""
        with pytest.raises(ValidationError):
            validate_instagram_url("")

    def test_non_string_url_raises(self):
        """URL non-string devrait lever ValidationError."""
        with pytest.raises(ValidationError):
            validate_instagram_url(123)

    def test_valid_post_count(self):
        """Nombre valide de posts."""
        assert validate_post_count(10) == 10

    def test_post_count_too_low_raises(self):
        """Nombre de posts < 1 devrait lever ValidationError."""
        with pytest.raises(ValidationError):
            validate_post_count(0)

    def test_post_count_too_high_raises(self):
        """Nombre de posts > 10000 devrait lever ValidationError."""
        with pytest.raises(ValidationError):
            validate_post_count(20000)

    def test_non_int_post_count_raises(self):
        """Nombre de posts non-int devrait lever ValidationError."""
        with pytest.raises(ValidationError):
            validate_post_count("10")


class TestPostDataStructure:
    """Tests de la structure PostData."""

    def test_postdata_has_required_fields(self):
        """PostData doit avoir url, caption, timestamp."""
        from scraper import PostData

        post = PostData(
            url="https://www.instagram.com/p/ABC123/",
            caption="Test caption",
            timestamp="2025-04-14T10:00:00+00:00",
        )

        assert post.url == "https://www.instagram.com/p/ABC123/"
        assert post.caption == "Test caption"
        assert post.timestamp == "2025-04-14T10:00:00+00:00"

    def test_postdata_with_empty_caption(self):
        """PostData avec caption vide est valide."""
        from scraper import PostData

        post = PostData(
            url="https://www.instagram.com/p/ABC123/",
            caption="",
            timestamp="2025-04-14T10:00:00+00:00",
        )

        assert post.caption == ""


class TestExceptions:
    """Tests des exceptions custom."""

    def test_selectors_outdated_error(self):
        """SelectorsOutdatedError peut être levée et attrapée."""
        from exceptions import SelectorsOutdatedError, SelectorError

        with pytest.raises(SelectorError):
            raise SelectorsOutdatedError("Test")

    def test_validation_error(self):
        """ValidationError peut être levée et attrapée."""
        from exceptions import ValidationError, InstagramScraperError

        with pytest.raises(InstagramScraperError):
            raise ValidationError("Test")


# Tests d'intégration (activer avec une vrai session)
@pytest.mark.integration
@pytest.mark.skip(reason="Requiert une vraie connexion Instagram")
def test_scraper_can_load_instagram_profile():
    """Test que le scraper peut charger un profil réel."""
    from scraper import InstagramScraper

    scraper = InstagramScraper(headless=True)
    posts = scraper.scrape("https://www.instagram.com/instagram", n=1)

    assert len(posts) > 0
    post = posts[0]
    assert post.url.startswith("https://www.instagram.com")
    assert isinstance(post.caption, str)
    assert isinstance(post.timestamp, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
