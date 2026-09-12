import pandas as pd

from ecom_ops.agents.sales import analyze_sales_dataframe


def test_sales_agent_flags_falling_coupon_and_low_stock():
    df = pd.DataFrame(
        [
            {"date": "2026-06-12", "sku": "SKU-FALL", "product_name": "Falling Item", "quantity": 10, "sales_amount": 100, "traffic": 500, "conversion_rate": 0.04, "stock": 3},
            {"date": "2026-06-13", "sku": "SKU-FALL", "product_name": "Falling Item", "quantity": 3, "sales_amount": 30, "traffic": 480, "conversion_rate": 0.01, "stock": 3},
            {"date": "2026-06-12", "sku": "SKU-RISE", "product_name": "Rising Item", "quantity": 2, "sales_amount": 20, "traffic": 100, "creator_material_count": 0},
            {"date": "2026-06-13", "sku": "SKU-RISE", "product_name": "Rising Item", "quantity": 8, "sales_amount": 80, "traffic": 180, "creator_material_count": 0},
        ]
    )

    result = analyze_sales_dataframe(df)

    assert "SKU-FALL" in set(result.coupon_application_list["sku"])
    assert "SKU-RISE" in set(result.creator_material_demand_list["sku"])
    assert "SKU-FALL" in set(result.high_risk_product_list["sku"])
    assert "Daily Sales Operation Summary" in result.markdown_summary


def test_sales_recommendations_include_required_fields():
    df = pd.DataFrame(
        [
            {"date": "2026-06-12", "sku": "SKU-A", "product_name": "Item A", "quantity": 5, "traffic": 300, "conversion_rate": 0.03},
            {"date": "2026-06-13", "sku": "SKU-A", "product_name": "Item A", "quantity": 1, "traffic": 250, "conversion_rate": 0.01},
        ]
    )

    result = analyze_sales_dataframe(df)
    row = result.high_risk_product_list.iloc[0]

    assert row["product_name"]
    assert row["sku"] == "SKU-A"
    assert row["data_reason"]
    assert row["risk_level"] in {"High", "Medium", "Low"}
    assert row["recommended_action"]
    assert row["priority_level"] in {"P1", "P2", "P3"}
