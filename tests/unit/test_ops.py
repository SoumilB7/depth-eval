"""ops/ — exact integer math, domains by evaluation, inverses."""

from depth_eval import NUMBER_OPS as O


def test_registry_has_all_permutations():
    assert len(O) == 18
    for a, b in [("n - x", "-n + x"), ("floor(n/x)", "floor(x/n)"),
                 ("Mod(n, x)", "Mod(x, n)"), ("n**x", "x**n")]:
        assert a in O and b in O


def test_matches_python_semantics_including_negatives():
    for nv in (-7, -1, 0, 3, 50):
        for xv in (-3, -1, 2, 7):
            assert O["floor(n/x)"].apply(nv, xv) == nv // xv
            assert O["Mod(n, x)"].apply(nv, xv) == nv % xv
            assert O["n + x"].apply(nv, xv) == nv + xv


def test_undefined_points_come_from_evaluation():
    assert not O["floor(n/x)"].defined_for(5, 0)
    assert not O["Mod(n, x)"].defined_for(0, 0)      # x substitutes before n
    assert not O["n**x"].defined_for(2, -1)          # 1/2 is not an integer
    assert not O["n/x"].defined_for(7, 2)            # exact division only
    assert O["n**x"].apply(0, 0) == 1
    assert O["n**x"].apply(2, 100) == 2**100         # exact, no floats


def test_inverse_table():
    assert O["n + x"].inverse == "n - x" and O["n - x"].inverse == "n + x"
    assert O["-n + x"].inverse == "-n + x"
    assert O["n*x"].inverse == "n/x" and O["n/x"].inverse == "n*x"
    assert O["Mod(n, x)"].inverse is None


def test_ops_only_accept_plain_ints():
    import pytest
    from depth_eval import At
    with pytest.raises(TypeError):
        O["n + x"].apply(5, At(3))
    with pytest.raises(TypeError):
        O["n + x"].apply(5, 2.0)
