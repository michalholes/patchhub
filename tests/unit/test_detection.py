"""Unit tests for core.detection module."""

from audiomason.core.detection import (
    detect_file_groups,
    detect_format,
    guess_author_from_path,
    guess_title_from_path,
    guess_year_from_path,
)


class TestGuessAuthorFromPath:
    """Tests for guess_author_from_path."""

    def test_author_dash_title_pattern(self, tmp_path):
        """Test 'Author - Title' pattern."""
        file = tmp_path / "George Orwell - 1984.m4a"
        file.touch()

        author = guess_author_from_path(file)
        assert author == "George Orwell"

    def test_lastname_firstname_pattern(self, tmp_path):
        """Test 'Lastname, Firstname' pattern."""
        file = tmp_path / "Orwell, George - 1984.m4a"
        file.touch()

        author = guess_author_from_path(file)
        assert author == "Orwell, George"

    def test_from_parent_directory(self, tmp_path):
        """Test extracting author from parent directory."""
        author_dir = tmp_path / "George Orwell"
        author_dir.mkdir()
        file = author_dir / "1984.m4a"
        file.touch()

        author = guess_author_from_path(file)
        assert author == "George Orwell"

    def test_returns_none_when_no_pattern_matches(self, tmp_path):
        """Test returns None when no pattern matches."""
        file = tmp_path / "audiobook.m4a"
        file.touch()

        # Should return None or directory name
        author = guess_author_from_path(file)
        assert author is None or author == tmp_path.name


class TestGuessTitleFromPath:
    """Tests for guess_title_from_path."""

    def test_author_dash_title_pattern(self, tmp_path):
        """Test extracting title from 'Author - Title' pattern."""
        file = tmp_path / "George Orwell - 1984.m4a"
        file.touch()

        title = guess_title_from_path(file)
        assert title == "1984"

    def test_title_with_year(self, tmp_path):
        """Test extracting title with year."""
        file = tmp_path / "Foundation (1951).m4a"
        file.touch()

        title = guess_title_from_path(file)
        assert title == "Foundation"

    def test_plain_filename(self, tmp_path):
        """Test plain filename as title."""
        file = tmp_path / "My Book.m4a"
        file.touch()

        title = guess_title_from_path(file)
        assert title == "My Book"


class TestGuessYearFromPath:
    """Tests for guess_year_from_path."""

    def test_year_in_parentheses(self, tmp_path):
        """Test year in (YYYY) format."""
        file = tmp_path / "Foundation (1951).m4a"
        file.touch()

        year = guess_year_from_path(file)
        assert year == 1951

    def test_year_in_brackets(self, tmp_path):
        """Test year in [YYYY] format."""
        file = tmp_path / "Foundation [1951].m4a"
        file.touch()

        year = guess_year_from_path(file)
        assert year == 1951

    def test_invalid_year_returns_none(self, tmp_path):
        """Test that invalid year returns None."""
        file = tmp_path / "Foundation (3000).m4a"
        file.touch()

        year = guess_year_from_path(file)
        assert year is None

    def test_no_year_returns_none(self, tmp_path):
        """Test that no year returns None."""
        file = tmp_path / "Foundation.m4a"
        file.touch()

        year = guess_year_from_path(file)
        assert year is None


class TestDetectFileGroups:
    """Tests for detect_file_groups."""

    def test_group_by_author(self, tmp_path):
        """Test grouping files by detected author."""
        files = [
            tmp_path / "Orwell, George - 1984.m4a",
            tmp_path / "Orwell, George - Animal Farm.m4a",
            tmp_path / "Asimov, Isaac - Foundation.m4a",
        ]

        for f in files:
            f.touch()

        groups = detect_file_groups(files)

        assert "Orwell, George" in groups
        assert len(groups["Orwell, George"]) == 2
        assert len(groups["Asimov, Isaac"]) == 1


class TestDetectFormat:
    """Tests for detect_format."""

    def test_detect_m4a(self, tmp_path):
        """Test detecting M4A format."""
        file = tmp_path / "book.m4a"
        file.touch()

        fmt = detect_format(file)
        assert fmt == "m4a"

    def test_detect_opus(self, tmp_path):
        """Test detecting Opus format."""
        file = tmp_path / "book.opus"
        file.touch()

        fmt = detect_format(file)
        assert fmt == "opus"

    def test_detect_mp3(self, tmp_path):
        """Test detecting MP3 format."""
        file = tmp_path / "book.mp3"
        file.touch()

        fmt = detect_format(file)
        assert fmt == "mp3"

    def test_unknown_format(self, tmp_path):
        """Test unknown format."""
        file = tmp_path / "book.xyz"
        file.touch()

        fmt = detect_format(file)
        assert fmt == "unknown"
