import re
from datetime import datetime

USER_INFO_REGEX = r"#registered_user_info\s*Ism-familiya: (.+?)\s*Telefon raqam: (.+?)\s*" \
                  r"Qo[’']shimcha telefon: (.+?)\s*Mahsulot/Xizmat/Kurs: (.+?)\s*Referal manbayi: (.+?)\s*$"


def check_register_info(message):
    """
    Checks the given message for user registration info using regex and returns a formatted notification if matched.

    Args:
        message (str): The message text to process.

    Returns:
        str: A formatted notification string if registration info is found, otherwise None.
    """
    registered_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Checking message for registration info: {message}")
    # Check if the message contains the registration tag
    if '#registered_user_info' in message:
        print("Found '#registered_user_info' in the message.")  # Log if the tag is found

        # Match the message against the regex pattern
        match = re.search(USER_INFO_REGEX, message, re.DOTALL)
        print(f"match: {match}")
        if match:
            print("Regex match successful!")  # Log if regex matches

            # Extract information from the message
            full_name, phone_number, additional_phone, course, referral_source = match.groups()

            # Create a formatted notification
            register_message = (
                f"\U00002705 New User Registered!\n\n"
                f"\U0001F464 Full Name: {full_name}\n"
                f"\U0001F4DE Phone Number: {phone_number}\n"
                f"\U0001F4F2 Additional Phone: {additional_phone}\n"
                f"\U0001F3EB Course: {course}\n"
                f"\U0001F4F0 Referral Source: {referral_source}\n"
                f"\U0001F4C5 Registered Date: {registered_date}"
            )
            return register_message
        else:
            print("Regex match failed.")  # Log if regex doesn't match

    return None  # Return None if no registration info is found


check_register_info("#registered_user_info Ism-familiya: John Doe\nTelefon raqam: +998901234567\n"
                    "Qo’shimcha telefon: +998901234567\nMahsulot/Xizmat/Kurs: Python\nReferal manbayi: Google")