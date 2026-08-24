from firstgreen.path_patterns import path_matches


def test_recursive_directory_pattern_matches_every_descendant() -> None:
    assert path_matches("packages/cli/src/index.ts", "packages/cli/**")
    assert path_matches("packages/cli/test.ts", "packages/cli/**")
    assert not path_matches("packages/core/index.ts", "packages/cli/**")


def test_single_star_does_not_cross_directory_boundary() -> None:
    assert path_matches("src/index.ts", "src/*.ts")
    assert not path_matches("src/nested/index.ts", "src/*.ts")
    assert path_matches("src/nested/index.ts", "src/**/*.ts")


def test_basename_pattern_keeps_pathlib_style_convenience() -> None:
    assert path_matches("src/nested/test_feature.py", "test_*.py")
    assert not path_matches("src/nested/feature.py", "test_*.py")
