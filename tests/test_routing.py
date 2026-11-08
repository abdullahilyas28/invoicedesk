from invoicedesk.schema import FieldConfidence
from invoicedesk.validate import ValidationResult, route_invoice


def make_confidence(**overrides) -> FieldConfidence:
    scores = {field_name: 1.0 for field_name in FieldConfidence.model_fields}
    scores.update(overrides)
    return FieldConfidence(**scores)


def test_clean_confident_invoice_is_auto_approved():
    decision = route_invoice(ValidationResult(failed_rules={}), make_confidence())
    assert decision.route == "auto_approve"
    assert decision.reasons == []


def test_failed_rule_goes_to_review():
    validation_result = ValidationResult(failed_rules={"gst_rate": "GST should be 31.47"})
    decision = route_invoice(validation_result, make_confidence())
    assert decision.route == "review"
    assert decision.reasons == ["gst_rate: GST should be 31.47"]


def test_low_confidence_goes_to_review():
    decision = route_invoice(ValidationResult(failed_rules={}), make_confidence(total=0.5))
    assert decision.route == "review"
    assert "total" in decision.reasons[0]