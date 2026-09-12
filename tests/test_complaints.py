import pandas as pd

from ecom_ops.agents.complaints import classify_complaints_dataframe


def test_complaint_classification_outputs_required_lists():
    df = pd.DataFrame(
        [
            {"order_id": "O1", "sku": "SKU-A", "product_name": "Lamp", "complaint_text": "The package was damaged in transit."},
            {"order_id": "O2", "sku": "SKU-B", "product_name": "Shelf", "complaint_text": "I bought the wrong size, unopened."},
            {"order_id": "O3", "sku": "SKU-C", "product_name": "Chair", "complaint_text": ""},
        ]
    )

    result = classify_complaints_dataframe(df)

    assert "Logistics damage" in set(result.complaint_registration["complaint_category"])
    assert "Good product" in set(result.good_or_suspected_good_products["product_condition"])
    assert "Needs human review" in set(result.human_review_list["product_condition"])
    assert result.complaint_registration["requires_human_confirmation"].all()


def test_complaint_recommendations_have_required_output_fields():
    df = pd.DataFrame(
        [{"sku": "SKU-D", "product_name": "Desk", "complaint_text": "Missing screws and accessories."}]
    )

    result = classify_complaints_dataframe(df)
    row = result.complaint_registration.iloc[0]

    assert row["product_name"]
    assert row["sku"] == "SKU-D"
    assert row["data_reason"]
    assert row["risk_level"] == "High"
    assert row["recommended_action"]
    assert row["priority_level"] == "P1"
