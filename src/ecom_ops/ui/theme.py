"""Visual system for the local operations workbench."""

WORKBENCH_CSS = """
<style>
    :root {
        --wb-ink: #17212b;
        --wb-muted: #5f6b76;
        --wb-border: #d7dee5;
        --wb-border-strong: #aeb9c4;
        --wb-surface: #ffffff;
        --wb-soft: #f1f4f6;
        --wb-canvas: #f6f8f9;
        --wb-primary: #0f766e;
        --wb-primary-hover: #0b5f59;
        --wb-primary-soft: #e5f5f2;
        --wb-danger: #b42318;
        --wb-warning: #9a6700;
        --wb-focus: #2c7be5;
    }

    .stApp {
        background: var(--wb-canvas);
        color: var(--wb-ink);
    }
    [data-testid="stHeader"] {
        background: rgba(246, 248, 249, .96);
        border-bottom: 1px solid #e8ecef;
    }
    .block-container {
        max-width: 1440px;
        padding-top: 1.35rem;
        padding-bottom: 3rem;
    }

    [data-testid="stSidebar"] {
        background: #17212b;
        border-right: 1px solid #263543;
    }
    [data-testid="stSidebar"] * {
        color: #eaf0f4;
    }
    [data-testid="stSidebar"] [role="radiogroup"] {
        gap: .24rem;
    }
    [data-testid="stSidebar"] [data-testid="stRadioOption"] {
        min-height: 2.25rem;
        padding: .28rem .55rem;
        border: 1px solid transparent;
        border-radius: 6px;
        transition: background-color .15s ease, border-color .15s ease;
    }
    [data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {
        background: #22313e;
        border-color: #314656;
    }
    [data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {
        background: #164e4a;
        border-color: #2b7f77;
    }
    [data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p {
        color: #ffffff !important;
        font-weight: 750;
    }
    [data-testid="stSidebar"] [data-testid="stAlert"] {
        background: #203249;
        border: 1px solid #304963;
    }
    [data-testid="stSidebar"] hr {
        border-color: #2b3b48;
    }
    .wb-brand {
        padding: .55rem .25rem 1.05rem;
    }
    .wb-brand-title {
        font-size: 1.18rem;
        font-weight: 800;
        letter-spacing: 0;
    }
    .wb-brand-sub {
        color: #9fb0bd !important;
        font-size: .72rem;
        margin-top: .18rem;
    }

    .wb-hero {
        background: var(--wb-surface);
        color: var(--wb-ink);
        padding: 1.25rem 1.45rem;
        border: 1px solid var(--wb-border);
        border-left: 5px solid var(--wb-primary);
        border-radius: 8px;
        margin-bottom: 1rem;
        box-shadow: 0 5px 18px rgba(23, 33, 43, .055);
    }
    .wb-eyebrow {
        color: var(--wb-primary);
        font-size: .72rem;
        font-weight: 800;
        letter-spacing: .06em;
    }
    .wb-hero h1 {
        color: var(--wb-ink);
        font-size: 1.7rem;
        line-height: 1.25;
        margin: .24rem 0 .32rem;
        letter-spacing: 0;
    }
    .wb-hero p {
        color: var(--wb-muted);
        margin: 0;
        max-width: 850px;
        line-height: 1.55;
    }

    .wb-card {
        background: var(--wb-surface);
        border: 1px solid var(--wb-border);
        border-radius: 8px;
        padding: 1rem 1.05rem;
        min-height: 128px;
        box-shadow: 0 3px 12px rgba(23, 33, 43, .035);
    }
    .wb-card-title {
        font-weight: 750;
        color: var(--wb-ink);
        margin-bottom: .24rem;
    }
    .wb-card-copy {
        font-size: .86rem;
        color: var(--wb-muted);
        line-height: 1.5;
    }
    .wb-badge {
        display: inline-block;
        padding: .2rem .5rem;
        border-radius: 999px;
        font-size: .72rem;
        font-weight: 750;
        margin-bottom: .52rem;
    }
    .wb-ok { color: #08634f; background: #dff5ee; }
    .wb-warn { color: #805600; background: #fff0c2; }
    .wb-off { color: #4f5d68; background: #e9eef2; }
    .wb-risk {
        border: 1px solid #f0d58a;
        border-left: 4px solid #d39a00;
        background: #fff9e8;
        color: #674d0a;
        padding: .72rem .9rem;
        border-radius: 6px;
        font-size: .84rem;
        margin: .5rem 0 1rem;
    }

    div[data-testid="stMetric"] {
        background: var(--wb-surface);
        border: 1px solid var(--wb-border);
        border-radius: 8px;
        padding: .75rem .9rem;
        box-shadow: 0 2px 8px rgba(23, 33, 43, .03);
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: var(--wb-ink);
        font-weight: 760;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid var(--wb-border);
        border-radius: 7px;
        overflow: hidden;
        background: var(--wb-surface);
    }

    [data-testid="stTabs"] [role="tablist"] {
        gap: .25rem;
        border-bottom: 1px solid var(--wb-border);
    }
    [data-testid="stTabs"] button[role="tab"] {
        min-height: 2.45rem;
        padding: .5rem .72rem;
        color: #53616d;
        font-weight: 650;
        border-bottom-color: transparent;
    }
    [data-testid="stTabs"] button[role="tab"]:hover {
        color: var(--wb-primary);
        background: var(--wb-primary-soft);
    }
    [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
        color: var(--wb-primary);
        border-bottom-color: var(--wb-primary);
        font-weight: 780;
    }

    button[kind="primary"],
    .stButton > button[kind="primary"],
    .stDownloadButton > button[kind="primary"] {
        background: var(--wb-primary) !important;
        border: 1px solid var(--wb-primary) !important;
        color: #ffffff !important;
        box-shadow: 0 1px 2px rgba(15, 118, 110, .22);
    }
    button[kind="primary"] *,
    .stButton > button[kind="primary"] * {
        color: #ffffff !important;
    }
    button[kind="primary"]:hover:not(:disabled) {
        background: var(--wb-primary-hover) !important;
        border-color: var(--wb-primary-hover) !important;
    }
    button[kind="secondary"],
    .stButton > button[kind="secondary"],
    .stDownloadButton > button,
    .stLinkButton > a {
        background: #ffffff !important;
        border: 1px solid var(--wb-border-strong) !important;
        color: #263541 !important;
        box-shadow: 0 1px 2px rgba(23, 33, 43, .04);
    }
    button[kind="secondary"] *,
    .stDownloadButton > button *,
    .stLinkButton > a * {
        color: #263541 !important;
    }
    button[kind="secondary"]:hover:not(:disabled),
    .stDownloadButton > button:hover:not(:disabled),
    .stLinkButton > a:hover {
        background: #edf7f5 !important;
        border-color: var(--wb-primary) !important;
        color: #0b5f59 !important;
    }
    button[kind="secondary"]:hover:not(:disabled) *,
    .stLinkButton > a:hover * {
        color: #0b5f59 !important;
    }
    .stButton > button,
    .stDownloadButton > button,
    .stLinkButton > a {
        min-height: 2.35rem;
        border-radius: 6px !important;
        font-weight: 720;
        transition: background-color .14s ease, border-color .14s ease, color .14s ease;
    }
    button:disabled,
    button[kind="primary"]:disabled,
    button[kind="secondary"]:disabled {
        opacity: 1 !important;
        background: #dfe5e9 !important;
        border-color: #aeb9c4 !important;
        color: #485762 !important;
        box-shadow: none !important;
        cursor: not-allowed !important;
    }
    button:disabled *,
    button[kind="primary"]:disabled *,
    button[kind="secondary"]:disabled *,
    .stButton > button[kind="primary"]:disabled * {
        color: #485762 !important;
    }
    button:focus-visible,
    a:focus-visible,
    input:focus-visible,
    textarea:focus-visible {
        outline: 3px solid rgba(44, 123, 229, .28) !important;
        outline-offset: 2px;
    }

    [data-testid="stFileUploaderDropzone"] {
        background: #ffffff;
        border: 1px dashed #aeb9c4;
        border-radius: 7px;
    }
    [data-testid="stFileUploaderDropzone"]:hover {
        border-color: var(--wb-primary);
        background: #f4fbf9;
    }
    [data-baseweb="select"] > div,
    [data-baseweb="input"] > div,
    [data-testid="stTextArea"] textarea,
    [data-testid="stNumberInput"] input {
        background: #ffffff !important;
        border-color: var(--wb-border-strong) !important;
        color: var(--wb-ink) !important;
        border-radius: 6px !important;
    }
    [data-baseweb="select"] > div:hover,
    [data-baseweb="input"] > div:hover,
    [data-testid="stTextArea"] textarea:hover {
        border-color: #72808d !important;
    }
    [data-testid="stAlert"] {
        border-radius: 7px;
        border-width: 1px;
    }
    [data-testid="stExpander"] {
        border-color: var(--wb-border);
        border-radius: 7px;
        background: var(--wb-surface);
    }

    @media (max-width: 640px) {
        .block-container {
            padding: .8rem 1rem 2rem;
        }
        .wb-hero {
            padding: 1rem 1rem;
            margin-bottom: .8rem;
        }
        .wb-hero h1 {
            font-size: 1.48rem;
        }
        .wb-hero p {
            font-size: .9rem;
        }
        [data-testid="stTabs"] [role="tablist"] {
            overflow-x: auto;
            scrollbar-width: thin;
        }
        [data-testid="stTabs"] button[role="tab"] {
            flex: 0 0 auto;
            white-space: nowrap;
        }
    }
</style>
"""
