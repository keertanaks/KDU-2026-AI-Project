import json
from typing import List, Dict, Union

from app.auth.models import UserRole


class MaskPolicy:
    POLICIES: Dict[str, List[str]] = {
        UserRole.TREATING_CLINICIAN: [],
        UserRole.NON_TREATING_CLINICIAN: ["PERSON", "NAME", "MRN", "ADDRESS", "PHONE", "DOB",
                                          "US_SSN", "US_PASSPORT", "PHONE_NUMBER",
                                          "EMAIL_ADDRESS", "IP_ADDRESS", "URL",
                                          "DATE_TIME", "LOCATION"],
        UserRole.ADMINISTRATOR: ["PERSON", "NAME", "MRN", "ADDRESS", "PHONE", "DOB",
                                 "US_SSN", "US_PASSPORT", "PHONE_NUMBER",
                                 "EMAIL_ADDRESS", "IP_ADDRESS", "URL",
                                 "DATE_TIME", "LOCATION",
                                 "DIAGNOSIS", "MEDICATION", "NRP", "MEDICAL_LICENSE"],
    }


class ResponseMasker:
    """Apply role-based PHI masking to a chunk of text."""

    @staticmethod
    def mask(chunk_text: str, phi_spans: Union[List[Dict], str], role: str) -> str:
        """
        Mask PHI spans in chunk_text according to the user's role.

        phi_spans may be a list of dicts or a JSON string (as stored in OpenSearch).
        """
        if isinstance(phi_spans, str):
            try:
                phi_spans = json.loads(phi_spans)
            except (json.JSONDecodeError, TypeError):
                phi_spans = []

        if not isinstance(phi_spans, list):
            phi_spans = []

        # Normalise role to enum for policy lookup
        try:
            role_enum = UserRole(role)
        except ValueError:
            role_enum = UserRole.NON_TREATING_CLINICIAN

        mask_types = set(MaskPolicy.POLICIES.get(role_enum, []))

        if not mask_types:
            return chunk_text

        text_list = list(chunk_text)
        # Apply spans in reverse order to preserve offsets
        sorted_spans = sorted(phi_spans, key=lambda x: x.get("start", 0), reverse=True)

        for span in sorted_spans:
            span_type = span.get("type", "")
            start = span.get("start", 0)
            end = span.get("end", 0)
            if span_type in mask_types and start < end <= len(text_list):
                # Add space before redaction tag if preceding char is alphanumeric
                prefix_space = " " if start > 0 and text_list[start - 1].isalnum() else ""
                # Add space after redaction tag if following char is alphanumeric
                suffix_space = " " if end < len(text_list) and text_list[end].isalnum() else ""
                replacement = list(f"{prefix_space}<{span_type}_REDACTED>{suffix_space}")
                text_list[start:end] = replacement

        return "".join(text_list)
