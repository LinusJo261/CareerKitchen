def test_quiet_hours_roundtrip_is_private_and_reports_resource_version(market):
    initial = market.call(0, "GET", "/notifications/preferences")
    assert initial.status_code == 200
    assert initial.json()["data"]["quiet_hours"] == {}
    hours = {"start": "22:00", "end": "07:00", "timezone": "America/Los_Angeles"}
    created = market.call(
        0,
        "PUT",
        "/notifications/preferences",
        {
            "expected_version": 1,
            "email_opt_in": False,
            "in_app_opt_in": True,
            "quiet_hours": hours,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["data"]["quiet_hours"] == hours
    version = created.json()["data"]["version"]
    assert created.json()["meta"]["resource_version"] == version
    fetched = market.call(0, "GET", "/notifications/preferences")
    assert fetched.json()["data"]["quiet_hours"] == hours
    assert fetched.json()["meta"]["resource_version"] == version
    assert market.call(1, "GET", "/notifications/preferences").json()["data"]["quiet_hours"] == {}
    updated = market.call(
        0,
        "PUT",
        "/notifications/preferences",
        {
            "expected_version": version,
            "email_opt_in": True,
            "in_app_opt_in": False,
            "quiet_hours": {},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["quiet_hours"] == {}
    stale = market.call(
        0,
        "PUT",
        "/notifications/preferences",
        {
            "expected_version": version,
            "email_opt_in": False,
            "in_app_opt_in": True,
            "quiet_hours": hours,
        },
    )
    assert stale.status_code == 412
