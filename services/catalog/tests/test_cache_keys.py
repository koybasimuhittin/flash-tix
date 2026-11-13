from catalog_svc.cache import detail_key, list_key, normalize_list_query


def test_equivalent_queries_share_a_key():
    a = normalize_list_query(" Istanbul ", "  Rock ", 20, 0)
    b = normalize_list_query("istanbul", "rock", 20, 0)
    assert a == b
    assert list_key(3, a) == list_key(3, b)


def test_empty_filters_are_the_same_as_missing_ones():
    assert normalize_list_query("", "   ", 20, 0) == normalize_list_query(None, None, 20, 0)


def test_different_queries_get_different_keys():
    base = normalize_list_query("istanbul", None, 20, 0)
    others = [
        normalize_list_query("ankara", None, 20, 0),
        normalize_list_query("istanbul", "jazz", 20, 0),
        normalize_list_query("istanbul", None, 10, 0),
        normalize_list_query("istanbul", None, 20, 20),
    ]
    keys = {list_key(1, query) for query in [base, *others]}
    assert len(keys) == 5


def test_list_version_is_part_of_the_key():
    query = normalize_list_query(None, None, 20, 0)
    assert list_key(1, query) != list_key(2, query)
    assert list_key(7, query).startswith("catalog:v1:events:7:")


def test_detail_key():
    assert detail_key(42) == "catalog:v1:event:42"
