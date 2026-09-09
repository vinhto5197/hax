"""Guards _eval_expr against unbounded operand growth (AR-2026-09-08 #1):
the exponent cap alone doesn't bound the RESULT of a chained pow/mult, so a
nested expression like ``((9**1000)**1000)**1000`` runs a synchronous
multi-million-bit big-int op on the event loop. The fix rejects the op before
computing when the resulting bit length would exceed _MAX_RESULT_BITS.
"""

import ast
import time

import pytest

from packages.core.agent.tools import _eval_expr


def _eval(expr: str):
    return _eval_expr(ast.parse(expr, mode="eval").body)


def test_nested_pow_rejected_fast():
    # Each inner pow already produces an operand whose bit_length blows the
    # guard for the next outer pow, so this must raise well before it can
    # start the (otherwise unbounded) computation.
    start = time.perf_counter()
    with pytest.raises(ValueError):
        _eval("((9**1000)**1000)**1000")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.2


def test_small_pow_still_works():
    assert _eval("2**10") == 1024


def test_chained_small_pow_still_works():
    assert _eval("(3**4)**2") == 6561


def test_large_but_bounded_mult_still_works():
    assert (
        _eval("12345678901234567890 * 98765432109876543210")
        == 12345678901234567890 * 98765432109876543210
    )
