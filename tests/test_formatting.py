from pyre.formatting import cents, fmt, new_id


class TestCents:
    def test_whole_dollars(self):
        assert cents("100") == 10000

    def test_dollars_and_cents(self):
        assert cents("7358.39") == 735839

    def test_one_cent(self):
        assert cents("0.01") == 1

    def test_zero(self):
        assert cents("0") == 0

    def test_float_input(self):
        assert cents(100) == 10000

    def test_negative(self):
        assert cents("-50.25") == -5025


class TestFmt:
    def test_positive(self):
        assert fmt(735839) == "$7,358.39"

    def test_negative(self):
        assert fmt(-735839) == "-$7,358.39"

    def test_zero(self):
        assert fmt(0) == "$0.00"

    def test_small_amount(self):
        assert fmt(1) == "$0.01"

    def test_exact_dollars(self):
        assert fmt(10000) == "$100.00"

    def test_millions(self):
        assert fmt(123456789) == "$1,234,567.89"

    def test_large_negative(self):
        assert fmt(-999999999) == "-$9,999,999.99"


class TestNewId:
    def test_length(self):
        assert len(new_id()) == 12

    def test_uniqueness(self):
        ids = {new_id() for _ in range(100)}
        assert len(ids) == 100
