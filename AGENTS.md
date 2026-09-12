# AGENTS.md

## Project Role

You are building a local automation system for cross-border e-commerce operations.

The system has two main agents:

1. Sales Data Analysis Agent
2. Complaint Registration Agent

The user is an e-commerce operator using Ziniao, Mabang ERP, and Leliao. The system should reduce repetitive manual work such as exporting tables, checking daily sales changes, classifying product risks, registering complaints, and preparing operation action reports.

## Development Rules

1. Use Python 3.11+.
2. Keep code modular and easy to maintain.
3. Do not hardcode credentials, API keys, passwords, cookies, or session tokens.
4. Use `.env` and `.env.example` for configuration.
5. Store raw files in `data/raw/`.
6. Store processed files in `data/processed/`.
7. Store output reports in `data/output/`.
8. Store screenshots in `data/screenshots/`.
9. Store logs for every run.
10. Use SQLite for local persistence.
11. Use pandas and openpyxl for Excel processing.
12. Use Playwright for browser automation templates.
13. Use Streamlit for the local UI.
14. Use FastAPI for local API endpoints.
15. Use pytest for tests.
16. Every risky business action must require human confirmation.
17. Never automatically submit refunds, replacement approvals, coupon applications, or product publishing.
18. Generate suggestions and reports only.
19. Browser automation must pause if login, captcha, or two-factor verification appears.
20. All browser selectors must be configurable in `config/selectors.yaml`.

## Business Logic

### Sales Agent

The Sales Agent should identify:

* Products with rising daily sales
* Products with falling daily sales
* Products at risk of losing traffic
* Products that need coupons
* Products that need creator materials
* Products with possible main image issues
* Products with possible price or conversion issues
* Products with low stock risk

The Sales Agent should generate:

* Daily sales report
* Coupon application list
* Creator material demand list
* High-risk product list
* Markdown summary for daily reporting

### Complaint Agent

The Complaint Agent should classify complaints into:

* Logistics damage
* Missing parts
* Usage problem
* Installation problem
* Quality issue
* Description mismatch
* Return/refund
* Delivery delay
* Customer mistaken purchase
* Malicious or unclear complaint
* Other

The Complaint Agent should classify product condition as:

* Good product
* Suspected good product
* Defective product
* Needs human review

The Complaint Agent should generate:

* Complaint registration Excel
* Complaint category summary
* Good/suspected good product list
* Defective product list
* Human review list

## Output Style

Reports should be practical for e-commerce operations.

Avoid vague suggestions. Every suggestion should contain:

* Product name or SKU
* Data reason
* Risk level
* Recommended action
* Priority level

## Safety Rules

1. Do not perform destructive actions.
2. Do not submit forms that change real business data unless explicitly enabled later.
3. Do not send messages to customers or creators automatically.
4. Do not refund, replace, delete, publish, or modify listings automatically.
5. Keep all sensitive data local.
6. Log all automation steps.
7. Make screenshots for important browser steps.
8. Make all AI decisions traceable.
