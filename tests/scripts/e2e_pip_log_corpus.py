# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Captured pip failure output, one shape per marker the box runner classifies on.

Data only — no assertions live here. The contract that consumes this corpus is
``test_e2e_runner_marker_coverage.py``, which binds these tables to the marker
lists actually shipped in ``tests/e2e/scripts/e2e-runner.sh`` and proves each
alternative is load-bearing. Split out of that module rather than inlined
because the two have different jobs and the combined file broke the 500-line
form budget.

Every log is a captured shape, not written from memory: pip 24.0 (the box
image's Ubuntu 24.04 pip) or pip 26.1 on the host, against unreachable and
degraded indexes and against deliberately malformed wheels. The ``#:`` comment
above each constant names the pip version and the condition that produces it.

Two invariants the consuming tests depend on, and the reason for the trimming
that may otherwise look arbitrary:

* a TRANSPORT log matches exactly ONE transport alternative, except for the
  three pairs real pip never prints apart (see ``SUBSUMED_TRANSPORT``);
* an ARTIFACT log matches exactly ONE artifact alternative.

A log carrying two alternatives from the same list proves neither, because
deleting either one leaves the other to classify it. That is why a build
failure appears here as a head and a tail in two separate constants.
"""

from __future__ import annotations

from tests.scripts.test_e2e_runner_install_resilience import (
    LOG_ARTIFACT_BAD_FILENAME,
    LOG_ARTIFACT_CORRUPT_WHEEL,
    LOG_NETWORK_READ_TIMEOUT,
)

# --------------------------------------------------------------------------
# Transport shapes. The degraded ones come first: a link that answers slowly,
# partially, or through something that is not the index is the condition the
# 2026-07-27 incident belongs to, and it was the condition with no coverage.
# --------------------------------------------------------------------------

#: pip 24.0, box image, against a peer that completes the TCP handshake and
#: then stops sending. The body arrives truncated at the 13 KiB/s the incident
#: measured. This is the archetypal *partial transfer*.
LOG_NETWORK_INCOMPLETE_READ = (
    "Downloading claude_agent_sdk-0.1.0-py3-none-any.whl (2.4 MB)\n"
    "   ---------------------------------------  0.9/2.4 MB 13.1 kB/s eta 0:01:54\n"
    "pip._vendor.urllib3.exceptions.IncompleteRead: IncompleteRead(943718 bytes read, "
    "1573042 more expected)\n"
)

#: pip 26.1, host, against a chunked response whose final chunk never arrives.
#: requests raises before urllib3's ``IncompleteRead`` is reachable, so this is
#: a distinct shape and not a re-spelling of the one above.
LOG_NETWORK_CHUNKED_ENCODING = (
    "pip._vendor.requests.exceptions.ChunkedEncodingError: "
    "('Connection broken: InvalidChunkLength(got length b'', 0 bytes read)', "
    "InvalidChunkLength(got length b'', 0 bytes read))\n"
)

#: pip 24.0, box image. The traceback frame urllib3 prints when a response body
#: dies mid-flight; pip echoes the whole traceback under ``ERROR: Exception:``.
#: The frame carries the exception class with no socket message attached, which
#: is why the class name has to be its own alternative.
LOG_NETWORK_PROTOCOL_ERROR = (
    "ERROR: Exception:\n"
    "Traceback (most recent call last):\n"
    '  File "/usr/lib/python3/dist-packages/pip/_vendor/urllib3/response.py", line 761, '
    "in _error_catcher\n"
    '    raise ProtocolError(f"Connection broken: {e!r}", e) from e\n'
)

#: pip 26.1, host. A middlebox closing the connection after the request: the
#: shape a corporate proxy or a hotel gateway produces mid-download.
LOG_NETWORK_CONNECTION_ABORTED = (
    "pip._vendor.requests.exceptions.ConnectionError: ('Connection aborted.', "
    "RemoteDisconnected('Remote end closed connection without response'))\n"
)

#: pip 24.0, box image. The peer resets an established connection. Errno-level
#: text with no urllib3 class name in the line, which is why the socket message
#: is its own alternative.
LOG_NETWORK_CONNECTION_RESET = "ConnectionResetError: [Errno 104] Connection reset by peer\n"

#: pip 26.1, host, against an address that swallows SYNs. The connect phase —
#: not the read phase — stalls until pip's own connect timeout fires. Note it
#: says "timed out" but NOT "Read timed out": the read-phase alternative does
#: not cover this.
LOG_NETWORK_CONNECT_TIMEOUT = (
    "Looking in indexes: https://pypi.org/simple\n"
    "WARNING: Retrying (Retry(total=7, connect=None, read=None, redirect=None, status=None)) "
    "after connection broken by 'ConnectTimeoutError(<pip._vendor.urllib3.connection."
    "HTTPSConnection object at 0x7f3c1a4d9e50>, 'Connection to pypi.org timed out. "
    "(connect timeout=60)')': /simple/bonfire-ai/\n"
)

#: pip 26.1, host, against an index answering 503 to every attempt. All eight
#: retries are spent and urllib3 gives up. The cause is a ``ResponseError``, so
#: no other transport alternative appears in the line.
LOG_NETWORK_RETRIES_EXHAUSTED = (
    "pip._vendor.urllib3.exceptions.MaxRetryError: HTTPSConnectionPool(host='pypi.org', "
    "port=443): Max retries exceeded with url: /simple/bonfire-ai/ "
    "(Caused by ResponseError('too many 503 error responses'))\n"
)

#: pip 24.0, box image, behind a TLS-terminating proxy presenting its own CA.
#: A captive portal or a corporate MITM box: the link is up, the peer is not
#: the index.
LOG_NETWORK_MITM_CERTIFICATE = (
    "WARNING: Retrying (Retry(total=7, connect=None, read=None, redirect=None, status=None)) "
    "after connection broken by 'SSLError(SSLCertVerificationError(1, "
    "'[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate "
    "(_ssl.c:1010)'))': /simple/bonfire-ai/\n"
)

#: pip 24.0, box image, behind a portal answering the index URL with its own
#: login page. pip does not raise here — it *skips* the URL and then reports
#: the package as unavailable, which is why this needs its own marker: without
#: it the log is indistinguishable from a genuinely missing package.
LOG_NETWORK_CAPTIVE_PORTAL = (
    "Looking in indexes: https://pypi.org/simple\n"
    "  Could not fetch URL https://pypi.org/simple/bonfire-ai/: 403 Client Error: Forbidden "
    "for url: https://pypi.org/simple/bonfire-ai/ - skipping\n"
    "ERROR: Could not find a version that satisfies the requirement bonfire-ai "
    "(from versions: none)\n"
)

#: pip 24.0, box image. The last line pip prints once the retries are gone: the
#: urllib3 class name is absent and only the socket message survives. A log
#: truncated to its tail — which is what a reader of a rotated Docker log gets
#: — matches on this alternative alone.
LOG_NETWORK_READ_TIMED_OUT_BARE = (
    "ERROR: Could not install packages due to an OSError: HTTPSConnectionPool("
    "host='files.pythonhosted.org', port=443): Read timed out.\n"
)

#: pip 26.1, host, with resolv.conf pointing at a reachable server that has no
#: record for the host. Name resolution failing a *second* way: the errno and
#: the message differ from the temporary-failure shape, and neither string
#: covers the other.
LOG_NETWORK_UNKNOWN_HOST = "socket.gaierror: [Errno -2] Name or service not known\n"

#: pip 24.0, box image. The DNS failure of the sibling module's
#: ``LOG_NETWORK_DNS``, reduced to the traceback line pip prints when the
#: resolver itself is what failed.
LOG_NETWORK_TEMPORARY_RESOLUTION_FAILURE = (
    "ERROR: Exception:\n"
    "Traceback (most recent call last):\n"
    "socket.gaierror: [Errno -3] Temporary failure in name resolution\n"
)

#: pip 24.0, box image with no default route. No socket is ever opened.
LOG_NETWORK_NO_ROUTE = "OSError: [Errno 101] Network is unreachable\n"

#: pip 26.1, host, against a closed port, reduced to the errno line. The
#: sibling module's ``LOG_NETWORK_REFUSED`` carries the same condition wrapped
#: in ``NewConnectionError``; this shape is what makes the socket message
#: load-bearing on its own.
LOG_NETWORK_CONNECTION_REFUSED_BARE = "ConnectionRefusedError: [Errno 111] Connection refused\n"

#: pip 26.1, host, against a host with no route. Deliberately a TWO-marker
#: shape: ``NewConnectionError`` and its own message text are the only markers
#: present, because urllib3 never prints one without the other. Errno 113's
#: message ("No route to host") is not itself a marker, which is what lets the
#: subsumption test say which of the two is carrying the verdict.
LOG_NETWORK_NEW_CONNECTION_PAIR = (
    "WARNING: Retrying (Retry(total=4, connect=None, read=None, redirect=None, status=None)) "
    "after connection broken by 'NewConnectionError('<pip._vendor.urllib3.connection."
    "HTTPSConnection object at 0x7f2b90c1d3a0>: Failed to establish a new connection: "
    "[Errno 113] No route to host')': /simple/bonfire-ai/\n"
)

#: Every shipped transport alternative, mapped to a captured log that exercises
#: it. Keys are compared for equality against the runner's own list.
TRANSPORT_FIXTURES: dict[str, str] = {
    "ReadTimeoutError": LOG_NETWORK_READ_TIMEOUT,
    "ConnectTimeoutError": LOG_NETWORK_CONNECT_TIMEOUT,
    "NewConnectionError": LOG_NETWORK_NEW_CONNECTION_PAIR,
    "MaxRetryError": LOG_NETWORK_RETRIES_EXHAUSTED,
    "ProtocolError": LOG_NETWORK_PROTOCOL_ERROR,
    "IncompleteRead": LOG_NETWORK_INCOMPLETE_READ,
    "ChunkedEncodingError": LOG_NETWORK_CHUNKED_ENCODING,
    "SSLError": LOG_NETWORK_MITM_CERTIFICATE,
    "Read timed out": LOG_NETWORK_READ_TIMED_OUT_BARE,
    "Failed to establish a new connection": LOG_NETWORK_NEW_CONNECTION_PAIR,
    "Temporary failure in name resolution": LOG_NETWORK_TEMPORARY_RESOLUTION_FAILURE,
    "Name or service not known": LOG_NETWORK_UNKNOWN_HOST,
    "Network is unreachable": LOG_NETWORK_NO_ROUTE,
    "Connection refused": LOG_NETWORK_CONNECTION_REFUSED_BARE,
    "Connection reset by peer": LOG_NETWORK_CONNECTION_RESET,
    "Connection aborted": LOG_NETWORK_CONNECTION_ABORTED,
    "Could not fetch URL": LOG_NETWORK_CAPTIVE_PORTAL,
}

#: The alternatives real pip cannot print alone, mapped to the alternative that
#: always accompanies them. Deleting one of a subsumed pair changes nothing;
#: deleting both is what flips the verdict, and
#: ``test_a_subsumed_transport_alternative_is_really_subsumed`` proves exactly
#: that, so this table cannot become a place to park an unproved marker.
SUBSUMED_TRANSPORT: dict[str, str] = {
    "ReadTimeoutError": "Read timed out",
    "NewConnectionError": "Failed to establish a new connection",
    "Failed to establish a new connection": "NewConnectionError",
}

#: The transport alternatives that must be provable ALONE.
SOLE_TRANSPORT = tuple(a for a in TRANSPORT_FIXTURES if a not in SUBSUMED_TRANSPORT)

# --------------------------------------------------------------------------
# Artifact shapes. Each is trimmed to the ONE alternative it proves, on
# purpose: a log carrying two artifact markers proves neither, because deleting
# either one leaves the other to classify it.
# --------------------------------------------------------------------------

#: pip 24.0, box image, against a wheel built for a different interpreter and
#: platform than the box's. pip reads the filename off the mount; no index is
#: consulted, so an unreachable one cannot manufacture this.
LOG_ARTIFACT_WRONG_PLATFORM_TAG = (
    "ERROR: bonfire_ai-1.0.1-cp312-cp312-macosx_14_0_arm64.whl is not a supported wheel "
    "on this platform.\n"
)

#: pip 24.0, box image, against an sdist whose build backend raises. Trimmed to
#: the tail deliberately: the head of this same failure
#: (``error: subprocess-exited-with-error``) is a separate alternative with its
#: own fixture below, and a fixture carrying both would prove neither.
LOG_ARTIFACT_WHEEL_BUILD_FAILED = (
    "  Building wheel for bonfire-ai (pyproject.toml): finished with status 'error'\n"
    "  ERROR: Failed building wheel for bonfire-ai\n"
    "ERROR: Failed to build installable wheels for some pyproject.toml based projects "
    "(bonfire-ai)\n"
)

#: pip 24.0, box image. The head of a build failure, trimmed for the same
#: reason as the tail above.
LOG_ARTIFACT_SUBPROCESS_EXITED = (
    "Processing /workspace/artifact/bonfire_ai-1.0.1.tar.gz\n"
    "  Installing build dependencies: started\n"
    "  Installing build dependencies: finished with status 'error'\n"
    "  error: subprocess-exited-with-error\n"
)

#: pip 24.0, box image. The metadata hook failing, on its own.
LOG_ARTIFACT_METADATA_GENERATION_FAILED = (
    "Processing /workspace/artifact/bonfire_ai-1.0.1.tar.gz\n"
    "  Preparing metadata (pyproject.toml): finished with status 'error'\n"
    "ERROR: metadata-generation-failed\n"
)

#: pip 26.1, host, against a malformed requirement string. Reachable without an
#: index: pip parses the requirement before it resolves anything.
LOG_ARTIFACT_INVALID_REQUIREMENT = (
    "ERROR: Invalid requirement: 'bonfire-ai==1.0.1=': Expected end or semicolon "
    "(after version specifier)\n"
    "    bonfire-ai==1.0.1=\n"
)

#: pip 26.1, host, with a constraint file that the wheel's own floors cannot
#: satisfy. The resolver reaches a contradiction it can name — distinct from
#: the honest ambiguity the runner's comment documents, where an unreachable
#: index means no version was ever *looked up*.
LOG_ARTIFACT_RESOLUTION_IMPOSSIBLE = (
    "ERROR: Cannot install bonfire-ai==1.0.1 because these package versions have "
    "conflicting dependencies.\n"
    "The conflict is caused by:\n"
    "    bonfire-ai 1.0.1 depends on pydantic>=2.7\n"
    "    The user requested (constraint) pydantic==1.10.15\n"
    "pip._vendor.resolvelib.resolvers.ResolutionImpossible: [Criterion([RequirementInformation("
    "requirement=SpecifierRequirement('pydantic>=2.7'), parent=None)])]\n"
)

#: pip 26.1, host, against a wheel whose ``METADATA`` carries an unparseable
#: ``Requires-Dist``. The wheel is a valid zip and pip still refuses it.
LOG_ARTIFACT_INVALID_METADATA = (
    "Processing /workspace/artifact/bonfire_ai-1.0.1-py3-none-any.whl\n"
    "ERROR: Package 'bonfire-ai' has invalid metadata: Expected matching "
    "RIGHT_PARENTHESIS for LEFT_PARENTHESIS, after version specifier\n"
    "    rich (>=13.7\n"
)

#: pip 24.0, box image, against an sdist that is not any archive format pip
#: recognises. pip has the bytes in hand and cannot open them.
LOG_ARTIFACT_CANNOT_UNPACK = (
    "Processing /workspace/artifact/bonfire_ai-1.0.1.tar.gz\n"
    "ERROR: Cannot unpack file /tmp/pip-unpack-8xk1v2n0/bonfire_ai-1.0.1.tar.gz (downloaded "
    "from /tmp/pip-req-build-3c9dlqya, content-type: application/octet-stream); cannot "
    "detect archive format\n"
)

#: Every shipped artifact alternative, mapped to a captured log carrying that
#: alternative and no other.
ARTIFACT_FIXTURES: dict[str, str] = {
    "ERROR: Wheel .* is invalid": LOG_ARTIFACT_CORRUPT_WHEEL,
    "Invalid wheel filename": LOG_ARTIFACT_BAD_FILENAME,
    "is not a supported wheel on this platform": LOG_ARTIFACT_WRONG_PLATFORM_TAG,
    "subprocess-exited-with-error": LOG_ARTIFACT_SUBPROCESS_EXITED,
    "metadata-generation-failed": LOG_ARTIFACT_METADATA_GENERATION_FAILED,
    "Failed building wheel": LOG_ARTIFACT_WHEEL_BUILD_FAILED,
    "ERROR: Invalid requirement": LOG_ARTIFACT_INVALID_REQUIREMENT,
    "ResolutionImpossible": LOG_ARTIFACT_RESOLUTION_IMPOSSIBLE,
    "has invalid metadata": LOG_ARTIFACT_INVALID_METADATA,
    "Cannot unpack file": LOG_ARTIFACT_CANNOT_UNPACK,
}

#: The degraded tail every artifact fixture is observed through. A link that is
#: slow and partial rather than dead is the condition the whole ordering rule
#: exists for, and it was the mixed direction with no coverage: the sibling
#: module's one mixed control rod uses a fully refused connection.
DEGRADED_TAIL = LOG_NETWORK_INCOMPLETE_READ

#: Named mixed shapes, in the degraded direction, with the transport half
#: varied and one case ordered artifact-first to prove the rule is not reading
#: position.
LOG_MIXED_CORRUPT_WHEEL_ON_PARTIAL_LINK = LOG_NETWORK_INCOMPLETE_READ + LOG_ARTIFACT_CORRUPT_WHEEL
LOG_MIXED_WRONG_PLATFORM_BEHIND_A_PORTAL = (
    LOG_NETWORK_CAPTIVE_PORTAL + LOG_ARTIFACT_WRONG_PLATFORM_TAG
)
LOG_MIXED_BUILD_CRASH_ON_A_STALLED_LINK = (
    LOG_NETWORK_READ_TIMED_OUT_BARE + LOG_ARTIFACT_SUBPROCESS_EXITED
)
LOG_MIXED_UNPACK_FAILURE_BEFORE_THE_LINK_DIED = (
    LOG_ARTIFACT_CANNOT_UNPACK + LOG_NETWORK_CHUNKED_ENCODING
)

#: Each mixed shape paired with its transport half. The pair is what makes the
#: assertion load-bearing: the mixed log must read ``artifact`` AND the
#: transport half alone must read ``network``, so the ordering rule is proved by
#: a difference rather than by one absolute.
MIXED_DEGRADED_SHAPES: dict[str, tuple[str, str]] = {
    "corrupt_wheel_on_partial_link": (
        LOG_MIXED_CORRUPT_WHEEL_ON_PARTIAL_LINK,
        LOG_NETWORK_INCOMPLETE_READ,
    ),
    "wrong_platform_behind_a_portal": (
        LOG_MIXED_WRONG_PLATFORM_BEHIND_A_PORTAL,
        LOG_NETWORK_CAPTIVE_PORTAL,
    ),
    "build_crash_on_a_stalled_link": (
        LOG_MIXED_BUILD_CRASH_ON_A_STALLED_LINK,
        LOG_NETWORK_READ_TIMED_OUT_BARE,
    ),
    "unpack_failure_before_the_link_died": (
        LOG_MIXED_UNPACK_FAILURE_BEFORE_THE_LINK_DIED,
        LOG_NETWORK_CHUNKED_ENCODING,
    ),
}
