# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# gmail-tools

- For Gmail inbox fetching, keep a server-side body normalization step as default behavior that strips signatures, legal disclaimers, unsubscribe footers, and tracking URL params (utm_*, etc.), and converts HTML to text. Make it opt-out via `body_processing="raw"`. Keep quoted replies (lines starting with `>` and `On ... wrote:` attribution) intact. Confidence: 0.85
- When user gives point feedback on what to simplify/remove, apply the change specifically to what was called out — do not over-correct by removing entire features (e.g., "don't strip quoted replies" does not mean "remove all body processing"). Confidence: 0.85
