"""
Skill: test_derive_if_then
Test routine for untested 'if-then' code path in derive_claims_from_text function.
"""

def test_derive_if_then():
    from .derive import derive_claims_from_text
    from .ir import Provenance

    # Create a provenance object
    prov = Provenance(source='test_source')

    # Define an if-then text
    text = 'If it rains then the ground is wet'

    # Call the function with the test text
    claims = derive_claims_from_text(text, prov)

    # Verify the results
    assert len(claims) == 1, "Expected one claim to be derived"
    assert claims[0].kind == "assertion", "Expected claim kind to be 'assertion'"
    assert "it" in claims[0].symbols, "Expected 'it' to be in symbols"
    assert "rains" in claims[0].symbols, "Expected 'rains' to be in symbols"
    assert "ground" in claims[0].symbols, "Expected 'ground' to be in symbols"
    assert "wet" in claims[0].symbols, "Expected 'wet' to be in symbols"

    print("If-Then test passed.")