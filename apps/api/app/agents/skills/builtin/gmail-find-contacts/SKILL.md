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

### GMAIL_GET_CONTACTS
Get contacts from email history using a search query.

**Best for:** Finding contacts - this is the most optimized tool for searching contacts

**Parameters:**
- query: Search query to filter contacts (REQUIRED - e.g., email address, name, or domain)
- max_results: Maximum number of messages to analyze (default: 30)

**Examples:**
- `query="john"` - Find contacts with "john" in name or email
- `query="company.com"` - Find contacts from specific domain
- `query="smith"` - Find contacts with "smith" in name or email


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

### GMAIL_FETCH_EMAILS
Search emails to find contact context.

**Useful for:**
- Finding recent emails with someone
- Getting email addresses from email threads
- Finding who introduced someone

## Workflow

### Finding a Contact (Recommended)

**Step 1: Use GMAIL_GET_CONTACTS with query**
- This is the most optimized tool for searching contacts
- Use query parameter to filter: `query="john"` or `query="john@company.com"`
- Set max_results higher for more thorough search (default 30)

**Step 2: Present Results**
Show user the matches:
```
Found contacts matching "john":
1. John Smith - john.smith@company.com
2. John Doe - john.doe@other.com

Want me to search for more?
```

### Alternative: Using GMAIL_SEARCH_PEOPLE

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

**Step 1: Use GMAIL_GET_CONTACTS**
- Fetches contacts from your email history
- Extracts unique email addresses you've interacted with

**Step 2: Present Results**
- Show count: "Found X contacts from your email history"
- Display first 10-20 with names and emails
- Offer to show more if needed

**Example:**
```
Found 156 contacts from your email history. Here are some:
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
