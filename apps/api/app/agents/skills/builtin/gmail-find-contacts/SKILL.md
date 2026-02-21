---
name: gmail-find-contacts
description: Find contacts in Gmail - search for specific people or email addresses from email history.
target: gmail_agent
---

# Gmail Find Contacts

## When to Use
- User asks "What's John's email?"
- User asks "Find contact information for..."
- User asks "Who have I emailed recently?"
- User asks "Get my contacts list"
- User wants to find someone's email address
- User needs to look up a person before sending email

## Tools

### GMAIL_SEARCH_PEOPLE
Find a specific person by name.

**Best for:** When user provides a name
- query: Name or partial name to search
- readMask: "names,emailAddresses,phoneNumbers" (include all)

**Returns:**
- List of matching people
- Email addresses
- Phone numbers (if available)
- Profile photos

### GET_CONTACT_LIST
Get comprehensive list of all contacts.

**Best for:** When user wants their full contact list

**Parameters:**
- max_results: Number of messages to analyze (default: 100)

**How it works:**
1. Fetches messages from inbox and sent
2. Parses email headers (From, To, Cc, Reply-To)
3. Extracts unique names and emails
4. Deduplicates results
5. Returns sorted list

### GMAIL_GET_PEOPLE
Get detailed info about specific person.

**Best for:** When you have a person ID
- personId: "people/c123456789" or "me" for own profile

**Returns:**
- Full name
- Email addresses
- Phone numbers
- Organization info
- Profile photo

### GMAIL_SEARCH_EMAILS
Search emails to find contact context.

**Useful for:**
- Finding recent emails with someone
- Getting email addresses from email threads
- Finding who introduced someone

## Workflow

### Finding Specific Person

**Step 1: Use GMAIL_SEARCH_PEOPLE**
- Enter name as query
- Request full readMask

**Step 2: Present Results**
Show user the matches:
```
Found 3 people named "John":
1. John Smith - john.smith@company.com
2. John Doe - john.doe@other.com
3. John Lee - john.lee@email.com

Which one?
```

**Step 3: Get Details (Optional)**
- Use GMAIL_GET_PEOPLE for more info
- Show organization, phone, etc.

### Getting Full Contact List

**Step 1: Use GET_CONTACT_LIST**
- Set max_results (default 100)
- More messages = more contacts

**Step 2: Present Results**
- Show count: "You have X contacts"
- Display first 10-20 with names and emails
- Offer to show more if needed

**Example:**
```
You have 156 contacts. Here are some:
- John Smith: john.smith@company.com
- Jane Doe: jane.doe@example.com
- Bob Wilson: bob.wilson@email.com
...

Want me to show more?
```

## Important Rules
1. **Verify before using** - Confirm correct person
2. **Ask for clarification** - If multiple matches, ask user
3. **Respect privacy** - Don't share details without purpose
4. **Handle not found** - If no results, suggest alternatives
5. **Use search** - If people search fails, try searching emails

## Tips
- Search by partial name works well
- Check recent emails for context
- Ask user which contact if unclear
- Offer to show more contacts if needed
