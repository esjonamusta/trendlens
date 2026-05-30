---
name: Obsidian Momentum
colors:
  surface: '#131314'
  surface-dim: '#131314'
  surface-bright: '#3a393a'
  surface-container-lowest: '#0e0e0f'
  surface-container-low: '#1c1b1c'
  surface-container: '#201f20'
  surface-container-high: '#2a2a2b'
  surface-container-highest: '#353436'
  on-surface: '#e5e2e3'
  on-surface-variant: '#bccbb9'
  inverse-surface: '#e5e2e3'
  inverse-on-surface: '#313031'
  outline: '#869585'
  outline-variant: '#3d4a3d'
  surface-tint: '#4ae176'
  primary: '#4be277'
  on-primary: '#003915'
  primary-container: '#22c55e'
  on-primary-container: '#004b1e'
  inverse-primary: '#006e2f'
  secondary: '#ffb95f'
  on-secondary: '#472a00'
  secondary-container: '#ee9800'
  on-secondary-container: '#5b3800'
  tertiary: '#ffb4ae'
  on-tertiary: '#68000a'
  tertiary-container: '#ff8a83'
  on-tertiary-container: '#860011'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#6bff8f'
  primary-fixed-dim: '#4ae176'
  on-primary-fixed: '#002109'
  on-primary-fixed-variant: '#005321'
  secondary-fixed: '#ffddb8'
  secondary-fixed-dim: '#ffb95f'
  on-secondary-fixed: '#2a1700'
  on-secondary-fixed-variant: '#653e00'
  tertiary-fixed: '#ffdad7'
  tertiary-fixed-dim: '#ffb3ad'
  on-tertiary-fixed: '#410004'
  on-tertiary-fixed-variant: '#930013'
  background: '#131314'
  on-background: '#e5e2e3'
  surface-variant: '#353436'
  surface-charcoal: '#121214'
  surface-raised: '#1C1C1F'
  border-subtle: '#2D2D30'
  text-muted: '#94A3B8'
  momentum-green: '#22C55E'
  momentum-orange: '#F59E0B'
  momentum-red: '#EF4444'
  accent-purple: '#818CF8'
typography:
  display-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: '1.4'
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '600'
    lineHeight: '1.0'
    letterSpacing: 0.1em
  metadata:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: '1.4'
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  container-max: 1120px
  gutter: 24px
  margin-mobile: 16px
  stack-sm: 8px
  stack-md: 16px
  stack-lg: 32px
  stack-xl: 64px
---

## Brand & Style

The design system is engineered for the high-velocity world of Product Management. It focuses on **Precision, Intelligence, and Momentum**. The brand personality is that of a "Silent Partner"—authoritative, sophisticated, and hyper-focused. It avoids the clutter of traditional dashboards, opting instead for a "Low-Noise, High-Signal" aesthetic.

The visual style is **Corporate Modern with Cyber-Tactile accents**. It utilizes a deep charcoal foundation to reduce eye strain during deep work, punctuated by vibrant, "glowing" indicators that represent market energy. Elements feel like physical hardware interfaces—precise, machined, and responsive—using subtle glassmorphism and thin borders to create a sense of advanced technology without the kitsch of retro-futurism.

## Colors

This design system uses a **True Dark** palette. The background is a near-black charcoal (`#0A0A0B`) to provide maximum contrast for the accent colors. 

### Semantic Palette
The colors are strictly functional, tied to the "velocity" of information:
- **Spiking (Primary):** A vibrant neon green (`#22C55E`) used for positive momentum and primary actions.
- **Stable (Secondary):** A rich amber/orange (`#F59E0B`) for steady-state signals.
- **Declining (Tertiary):** A sharp coral red (`#EF4444`) for fading trends.
- **System (Accent):** An indigo-purple (`#818CF8`) is used sparingly for UI-specific states like active filters or selection toggles.

Colors should be applied with "glowing" properties (inner glows and drop shadows) only on momentum-related components to maintain the metaphor of active energy.

## Typography

The typography strategy prioritizes readability and information hierarchy. 

- **Headlines:** Use **Plus Jakarta Sans**. It provides a modern, slightly geometric feel that remains friendly and professional. Bold weights and tight letter spacing are used for primary headings to create a "locked-in" look.
- **Body:** Use **Inter**. This is the workhorse of the design system, ensuring that long-form trend summaries are legible across all devices.
- **Data & Metadata:** Use **JetBrains Mono** for status labels, momentum tags, and timestamps. The monospaced nature emphasizes the "intelligence/data" aspect of the product.

High contrast is essential. Use pure white (`#FFFFFF`) for headlines and `text-muted` (`#94A3B8`) for secondary information to create clear visual layers.

## Layout & Spacing

This design system uses a **Fixed Grid** approach for the core dashboard to ensure the "Top 3 Trends" are always presented with maximum focus and no horizontal distraction.

- **Desktop:** 12-column grid centered in a 1120px container.
- **Tablet:** 8-column grid with fluid margins.
- **Mobile:** Single column stack with 16px safe-area margins.

The spacing follows a strict **8px power-of-two rhythm**. Large vertical gaps (`stack-xl`) are used to separate the three core trend cards, ensuring each signal has "room to breathe" and is processed as a distinct entity.

## Elevation & Depth

Depth is achieved through **Tonal Layering** rather than traditional heavy shadows.

1.  **Level 0 (Background):** Pure charcoal `#0A0A0B`.
2.  **Level 1 (Cards/Containers):** Raised charcoal `#121214`. These feature a 1px solid border in `#2D2D30`.
3.  **Level 2 (Active States/Modals):** Lighter charcoal `#1C1C1F`.

**Glow Effects:**
Momentum tags (Spiking, Stable, Declining) use a specialized "Energy Glow." This consists of a subtle 10px outer blur and a 1px inner stroke, both utilizing the semantic color of the tag. This creates the illusion of the component being "powered on."

## Shapes

The shape language is **Rounded**, leaning towards a premium hardware feel. 

- **Standard Elements:** 0.5rem (8px) for cards and input fields.
- **Buttons & Tags:** 1.5rem (24px) for a "pill" shape that contrasts against the rectangular cards.

This mixture of radius levels helps differentiate between "structural" components (cards) and "interactive" components (buttons/chips).

## Components

### Cards (Trend Cards)
- **Background:** `#121214`.
- **Border:** 1px solid `#2D2D30`.
- **Inner Padding:** 24px.
- **Feature:** Must contain a momentum sparkline (simplified trend graph) next to the momentum tag.

### Momentum Tags
- **Style:** Pill-shaped with a dark fill and a colored inner-stroke.
- **States:**
    - **Spiking:** Green text, green 1px inner-glow, green icon.
    - **Stable:** Orange text, orange 1px inner-glow, orange icon.
    - **Declining:** Red text, red 1px inner-glow, red icon.

### Buttons
- **Primary:** Pill-shaped, neon green background with black text for high impact.
- **Secondary (Re-run/Filter):** Pill-shaped, dark border, white text, no background fill.

### Input Fields
- **Style:** Understated. Dark background (`#1C1C1F`) with a subtle 1px border. Focus state should trigger the indigo-purple (`#818CF8`) border and a soft glow.

### Feedback Loop (Upvote/Downvote)
- Small, circular icon buttons. 
- Use low-opacity gray in neutral state; primary green/tertiary red when active.