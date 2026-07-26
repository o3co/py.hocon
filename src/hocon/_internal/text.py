# Copyright 2026 1o1 Co. Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Text normalisation shared by the adapters (spec F0.9)."""

_BOM = "﻿"


def strip_bom(text: str) -> str:
    """Drop a leading BOM.

    Reading a file as ``utf-8-sig`` covers the file entry points, but the text
    entry points take a ``str`` the caller decoded themselves — and a BOM left
    in place becomes part of the first key, so the file parses and the value is
    simply unreachable. F0.9 names that as the failure mode to avoid, being
    worse than an error.

    Only a *leading* BOM is removed. Elsewhere U+FEFF is ordinary data.
    """
    return text[1:] if text.startswith(_BOM) else text
