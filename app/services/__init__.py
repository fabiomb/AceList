"""Service layer: each public function is one unit of work and commits on success.

The session is injected by the caller. On failure the session is rolled back
and a `ServiceError` subclass is raised.
"""
