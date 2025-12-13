"""
Service functions for handling contact-related operations.
"""

from typing import Dict, List, Any

from app.config.loggers import chat_logger as logger
from app.services.mail_service import search_messages


def _process_message_batch(
    service, message_ids: List[str], filter_query: str | None = None
) -> Dict[str, Dict[str, str]]:
    """
    Process a batch of message IDs and extract contacts using Gmail batch API.

    Args:
        service: Gmail service instance
        message_ids: List of message IDs to process
        filter_query: Optional query to filter contacts

    Returns:
        Dictionary of contacts (email -> contact info)
    """
    contact_dict = {}

    try:
        # Use Gmail batch request for better performance
        batch = service.new_batch_http_request()

        def add_message_callback(request_id, response, exception):
            if exception:
                logger.warning(
                    f"CONTACT_SERVICE: Error in batch request for message {request_id}: {exception}"
                )
                return

            try:
                # Extract headers
                headers = {
                    h["name"]: h["value"]
                    for h in response.get("payload", {}).get("headers", [])
                }

                # Extract contacts from headers
                for field in ["From", "To", "Cc", "Reply-To"]:
                    if field in headers and headers[field]:
                        addresses = headers[field].split(",")

                        for address in addresses:
                            address = address.strip()
                            if not address:
                                continue

                            name = ""
                            email = address

                            # Handle format: "Name <email@example.com>"
                            if "<" in address and ">" in address:
                                name = address.split("<")[0].strip()
                                email = address.split("<")[1].split(">")[0].strip()

                            # Only add if it's a valid email address
                            if "@" in email and "." in email:
                                # Apply filter if provided
                                if filter_query:
                                    query_lower = filter_query.lower()
                                    name_lower = name.lower() if name else ""
                                    email_lower = email.lower()

                                    if (
                                        query_lower in name_lower
                                        or query_lower in email_lower
                                        or name_lower.startswith(query_lower)
                                        or email_lower.startswith(query_lower)
                                    ):
                                        contact_dict[email] = {
                                            "name": name,
                                            "email": email,
                                        }
                                else:
                                    contact_dict[email] = {"name": name, "email": email}

            except Exception as e:
                logger.warning(
                    f"CONTACT_SERVICE: Error processing message in batch: {e}"
                )

        # Add all messages to the batch request
        for msg_id in message_ids:
            batch.add(
                service.users().messages().get(userId="me", id=msg_id, format="full"),
                callback=add_message_callback,
                request_id=msg_id,
            )

        # Execute the batch request
        batch.execute()

    except Exception as e:
        logger.error(f"CONTACT_SERVICE: Error in batch processing: {e}")
        # Fallback to individual requests if batch fails
        return _process_messages_individually(service, message_ids, filter_query)

    return contact_dict


def _process_messages_individually(
    service, message_ids: List[str], filter_query: str | None = None
) -> Dict[str, Dict[str, str]]:
    """
    Fallback method to process messages individually if batch processing fails.
    """
    contact_dict = {}

    for msg_id in message_ids[:20]:  # Limit to 20 messages for fallback
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
            headers = {
                h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])
            }

            for field in ["From", "To", "Cc", "Reply-To"]:
                if field in headers and headers[field]:
                    addresses = headers[field].split(",")

                    for address in addresses:
                        address = address.strip()
                        if not address:
                            continue

                        name = ""
                        email = address

                        if "<" in address and ">" in address:
                            name = address.split("<")[0].strip()
                            email = address.split("<")[1].split(">")[0].strip()

                        if "@" in email and "." in email:
                            if filter_query:
                                query_lower = filter_query.lower()
                                name_lower = name.lower() if name else ""
                                email_lower = email.lower()

                                if (
                                    query_lower in name_lower
                                    or query_lower in email_lower
                                    or name_lower.startswith(query_lower)
                                    or email_lower.startswith(query_lower)
                                ):
                                    contact_dict[email] = {"name": name, "email": email}
                            else:
                                contact_dict[email] = {"name": name, "email": email}

        except Exception as e:
            logger.warning(f"CONTACT_SERVICE: Error processing message {msg_id}: {e}")
            continue

    return contact_dict


def extract_contacts_from_messages_batch(
    service,
    message_ids: List[str],
    filter_query: str | None = None,
    batch_size: int = 50,
) -> List[Dict[str, str]]:
    """
    Extract contacts from the given message IDs using batch processing for better performance.

    Args:
        service: The Gmail service instance
        message_ids: List of message IDs to extract contacts from
        filter_query: Optional query to filter contacts by name/email
        batch_size: Number of messages to process in each batch

    Returns:
        List of contacts with name and email
    """
    logger.info(
        f"CONTACT_SERVICE: Starting to extract contacts from {len(message_ids)} messages using batch processing"
    )

    # Limit the number of messages to process for performance
    max_messages = min(len(message_ids), 100)  # Process max 100 messages
    message_ids = message_ids[:max_messages]

    contact_dict = {}  # To ensure uniqueness

    # Process messages in batches for better performance
    for batch_start in range(0, len(message_ids), batch_size):
        batch_end = min(batch_start + batch_size, len(message_ids))
        batch_ids = message_ids[batch_start:batch_end]

        logger.debug(
            f"CONTACT_SERVICE: Processing batch {batch_start // batch_size + 1}: {len(batch_ids)} messages"
        )

        # Use batch request to fetch multiple messages at once
        batch_contacts = _process_message_batch(service, batch_ids, filter_query)

        # Merge batch results
        contact_dict.update(batch_contacts)

    # Convert dict to list
    contacts = list(contact_dict.values())

    # Sort contacts alphabetically by name, then email
    contacts.sort(key=lambda x: (x["name"] if x["name"] else x["email"]))

    logger.info(
        f"CONTACT_SERVICE: Extracted {len(contacts)} unique contacts from {len(message_ids)} messages"
    )
    logger.debug(f"CONTACT_SERVICE: Contacts found: {contacts}")

    return contacts


def get_gmail_contacts(
    service,
    query: str,
    max_results: int = 30,
) -> Dict[str, Any]:
    """
    Search for contacts in Gmail using a query.

    Args:
        service: The Gmail service instance
        query: Search query to filter contacts (e.g., email address, name, or any Gmail search query)
        max_results: Maximum number of messages to analyze for contact extraction

    Returns:
        Dictionary with contacts information
    """
    try:
        logger.info(
            f"CONTACT_SERVICE: Starting contact search with query: '{query}', max_results: {max_results}"
        )

        # Optimized search strategy - use the most effective single query
        # Using quoted search which searches across all fields efficiently
        search_query = f'"{query}"'
        logger.debug(f"CONTACT_SERVICE: Using optimized search query: '{search_query}'")

        search_results = search_messages(
            service=service, query=search_query, max_results=max_results
        )

        message_ids = [msg.get("id") for msg in search_results.get("messages", [])]
        logger.info(f"CONTACT_SERVICE: Search returned {len(message_ids)} messages")

        # If messages found, extract contacts using optimized batch processing
        if message_ids:
            logger.info(
                f"CONTACT_SERVICE: Extracting contacts from {len(message_ids)} message IDs using batch processing"
            )
            contacts = extract_contacts_from_messages_batch(
                service, message_ids, filter_query=query
            )

            result = {
                "success": True,
                "contacts": contacts,
                "count": len(contacts),
            }
            logger.info(
                f"CONTACT_SERVICE: Returning {len(contacts)} contacts for query '{query}'"
            )
            return result
        else:
            logger.info(f"CONTACT_SERVICE: No messages found for query '{query}'")
            return {
                "success": True,
                "contacts": [],
                "count": 0,
                "message": f"No messages found matching query: {query}",
            }

    except Exception as e:
        error_msg = f"CONTACT_SERVICE: Error getting Gmail contacts for query '{query}': {str(e)}"
        logger.error(error_msg)
        logger.exception("CONTACT_SERVICE: Full traceback:")
        return {"success": False, "error": error_msg, "contacts": []}
