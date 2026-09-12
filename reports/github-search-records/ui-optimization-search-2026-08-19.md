# UI optimization GitHub search record

Date: 2026-08-19

## Search queries

- Streamlit dashboard UI components MIT theme beautiful
- streamlit shadcn components MIT
- Streamlit Ant Design components MIT dashboard
- Streamlit Material UI dashboard MIT
- Streamlit navigation bar MIT

## Projects reviewed

| Project | License / status | Useful ideas | Decision |
| --- | --- | --- | --- |
| streamlit/streamlit | Apache-2.0 | Native light/dark theme tokens, sidebar-specific colors, widget borders and radius controls | Use native theme configuration as the base |
| ObservedObserver/streamlit-shadcn-ui | MIT | High-contrast button variants, restrained surfaces, compact controls and consistent states | Visual reference only; avoid adding another component runtime |
| okld/streamlit-elements | MIT | Dense operational dashboards, clear action hierarchy, Material UI interaction states | Visual and layout reference only |
| nicedouble/StreamlitAntdComponentsDemo | Demo for streamlit-antd-components | Compact tabs, menus and status feedback | Reference only; no dependency needed |
| gabrieltempass/streamlit-navigation-bar | MIT | Active navigation contrast and theme-aware navigation | Reference only; preserve the existing sidebar workflow |
| arnaudmiribel/streamlit-extras | Apache-2.0 | Focused utility components and consistent component packaging | Not needed for the current contrast/style fix |

## Implementation decision

Keep the current Streamlit application and local React timeline. Apply a native
Streamlit theme plus a small, selector-based CSS layer inspired by shadcn and
Material UI state conventions:

- dark teal primary actions with white text;
- white secondary actions with dark text and visible borders;
- clearly muted but readable disabled controls;
- compact 6-8 px radii;
- solid surfaces instead of gradients;
- stronger focus, hover, active-tab and input states;
- separate warning, success and destructive action colors;
- preserve responsive behavior and avoid a framework migration.

## Sources

- https://github.com/streamlit/streamlit
- https://github.com/ObservedObserver/streamlit-shadcn-ui
- https://github.com/okld/streamlit-elements
- https://github.com/nicedouble/StreamlitAntdComponentsDemo
- https://github.com/gabrieltempass/streamlit-navigation-bar
- https://github.com/arnaudmiribel/streamlit-extras
