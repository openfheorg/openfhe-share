from app.core.mysql.UserRole import UserRole


def test_user_role_values_are_strings():
    assert str(UserRole.ADMIN) == "ADMIN"
    assert UserRole.CLIENT.value == "CLIENT"
