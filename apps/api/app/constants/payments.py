"""
Payment and billing constants.
"""

# How many charges a payment-history read returns. Deep history belongs in the
# billing portal; the agent only ever needs "what have I been charged lately".
PAYMENT_HISTORY_LIMIT = 10

NO_USER_MESSAGE = "Could not identify the user, so their billing state is unavailable."
