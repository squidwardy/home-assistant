"""Auth providers for Home Assistant."""
import importlib
import logging
import types
from typing import Any, Dict, List, Optional

import voluptuous as vol
from voluptuous.humanize import humanize_error

from homeassistant import data_entry_flow, requirements
from homeassistant.core import callback, HomeAssistant
from homeassistant.const import CONF_TYPE, CONF_NAME, CONF_ID
from homeassistant.util.decorator import Registry

from homeassistant.auth.auth_store import AuthStore
from homeassistant.auth.models import Credentials, UserMeta

_LOGGER = logging.getLogger(__name__)
DATA_REQS = 'auth_prov_reqs_processed'

AUTH_PROVIDERS = Registry()

AUTH_PROVIDER_SCHEMA = vol.Schema({
    vol.Required(CONF_TYPE): str,
    vol.Optional(CONF_NAME): str,
    # Specify ID if you have two auth providers for same type.
    vol.Optional(CONF_ID): str,
}, extra=vol.ALLOW_EXTRA)


class AuthProvider:
    """Provider of user authentication."""

    DEFAULT_TITLE = 'Unnamed auth provider'

    def __init__(self, hass: HomeAssistant, store: AuthStore,
                 config: Dict[str, Any]) -> None:
        """Initialize an auth provider."""
        self.hass = hass
        self.store = store
        self.config = config

    @property
    def id(self) -> Optional[str]:  # pylint: disable=invalid-name
        """Return id of the auth provider.

        Optional, can be None.
        """
        return self.config.get(CONF_ID)

    @property
    def type(self) -> str:
        """Return type of the provider."""
        return self.config[CONF_TYPE]  # type: ignore

    @property
    def name(self) -> str:
        """Return the name of the auth provider."""
        return self.config.get(CONF_NAME, self.DEFAULT_TITLE)

    async def async_credentials(self) -> List[Credentials]:
        """Return all credentials of this provider."""
        users = await self.store.async_get_users()
        return [
            credentials
            for user in users
            for credentials in user.credentials
            if (credentials.auth_provider_type == self.type and
                credentials.auth_provider_id == self.id)
        ]

    @callback
    def async_create_credentials(self, data: Dict[str, str]) -> Credentials:
        """Create credentials."""
        return Credentials(
            auth_provider_type=self.type,
            auth_provider_id=self.id,
            data=data,
        )

    # Implement by extending class

    async def async_credential_flow(
            self, context: Optional[Dict]) -> data_entry_flow.FlowHandler:
        """Return the data flow for logging in with auth provider."""
        raise NotImplementedError

    async def async_get_or_create_credentials(
            self, flow_result: Dict[str, str]) -> Credentials:
        """Get credentials based on the flow result."""
        raise NotImplementedError

    async def async_user_meta_for_credentials(
            self, credentials: Credentials) -> UserMeta:
        """Return extra user metadata for credentials.

        Will be used to populate info when creating a new user.
        """
        raise NotImplementedError


async def auth_provider_from_config(
        hass: HomeAssistant, store: AuthStore,
        config: Dict[str, Any]) -> Optional[AuthProvider]:
    """Initialize an auth provider from a config."""
    provider_name = config[CONF_TYPE]
    module = await load_auth_provider_module(hass, provider_name)

    if module is None:
        return None

    try:
        config = module.CONFIG_SCHEMA(config)  # type: ignore
    except vol.Invalid as err:
        _LOGGER.error('Invalid configuration for auth provider %s: %s',
                      provider_name, humanize_error(config, err))
        return None

    return AUTH_PROVIDERS[provider_name](hass, store, config)  # type: ignore


async def load_auth_provider_module(
        hass: HomeAssistant, provider: str) -> Optional[types.ModuleType]:
    """Load an auth provider."""
    try:
        module = importlib.import_module(
            'homeassistant.auth.providers.{}'.format(provider))
    except ImportError:
        _LOGGER.warning('Unable to find auth provider %s', provider)
        return None

    if hass.config.skip_pip or not hasattr(module, 'REQUIREMENTS'):
        return module

    processed = hass.data.get(DATA_REQS)

    if processed is None:
        processed = hass.data[DATA_REQS] = set()
    elif provider in processed:
        return module

    # https://github.com/python/mypy/issues/1424
    reqs = module.REQUIREMENTS  # type: ignore
    req_success = await requirements.async_process_requirements(
        hass, 'auth provider {}'.format(provider), reqs)

    if not req_success:
        return None

    processed.add(provider)
    return module
