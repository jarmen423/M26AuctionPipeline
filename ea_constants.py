"""EA Companion constants translated from snallabot-service for Python call sites."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, TypedDict


# OAuth / Companion login configuration
AUTH_SOURCE = 317239
CLIENT_SECRET = "wfGAWnrxLroZOwwELYA2ZrAuaycuF2WDb00zOLv48Sb79viJDGlyD6OyK8pM5eIiv_20240731135155"
REDIRECT_URL = "http://127.0.0.1/success"
CLIENT_ID = "MCA_25_COMP_APP"
MACHINE_KEY = "444d362e8e067fe2"
EA_LOGIN_URL = (
	"https://accounts.ea.com/connect/auth"
	"?hide_create=true&release_type=prod&response_type=code"
	f"&redirect_uri={REDIRECT_URL}&client_id={CLIENT_ID}&machineProfileKey={MACHINE_KEY}"
	f"&authentication_source={AUTH_SOURCE}"
)


# Madden version configuration
TWO_DIGIT_YEAR = "25"
YEAR = "2026"


def _system_map(two_digit_year: str) -> Dict[str, str]:
	return {
		"xone": f"MADDEN_{two_digit_year}_XONE_BLZ_SERVER",
		"ps4": f"MADDEN_{two_digit_year}_PS4_BLZ_SERVER",
		"pc": f"MADDEN_{two_digit_year}_PC_BLZ_SERVER",
		"ps5": f"MADDEN_{two_digit_year}_PS5_BLZ_SERVER",
		"xbsx": f"MADDEN_{two_digit_year}_XBSX_BLZ_SERVER",
		"stadia": f"MADDEN_{two_digit_year}_SDA_BLZ_SERVER",
	}


SYSTEM_MAP = _system_map(TWO_DIGIT_YEAR)


NAMESPACES = {
	"xbox": "XBOX",
	"ps3": "PSN",
	"cem_ea_id": "EA Account",
	"stadia": "Stadia",
}


def _blaze_service(year: str) -> Dict[str, str]:
	return {
		"xone": f"madden-{year}-xone",
		"ps4": f"madden-{year}-ps4",
		"pc": f"madden-{year}-pc",
		"ps5": f"madden-{year}-ps5",
		"xbsx": f"madden-{year}-xbsx",
		"stadia": f"madden-{year}-stadia",
	}


BLAZE_SERVICE = _blaze_service(YEAR)


def _service_to_path(year: str) -> Dict[str, str]:
	return {
		f"madden-{year}-xone-gen4": "xone",
		f"madden-{year}-ps4-gen4": "ps4",
		f"madden-{year}-pc-gen5": "pc",
		f"madden-{year}-ps5-gen5": "ps5",
		f"madden-{year}-xbsx-gen5": "xbsx",
		f"madden-{year}-stadia-gen5": "stadia",
	}


BLAZE_SERVICE_TO_PATH = _service_to_path(YEAR)


def _product_names(year: str) -> Dict[str, str]:
	return {
		"xone": f"madden-{year}-xone-mca",
		"ps4": f"madden-{year}-ps4-mca",
		"pc": f"madden-{year}-pc-mca",
		"ps5": f"madden-{year}-ps5-mca",
		"xbsx": f"madden-{year}-xbsx-mca",
		"stadia": f"madden-{year}-stadia-mca",
	}


BLAZE_PRODUCT_NAME = _product_names(YEAR)


# Companion API typing helpers
Namespace = Literal["xbox", "ps3", "cem_ea_id", "stadia"]


class AccountToken(TypedDict):
	access_token: str
	expires_in: int
	id_token: None
	refresh_token: str
	token_type: Literal["Bearer"]


class TokenInfo(TypedDict):
	client_id: Literal["MCA_25_COMP_APP"]
	expires_in: int
	persona_id: None
	pid_id: str
	pid_type: Literal["NUCLEUS"]
	scope: str
	user_id: str


class Entitlement(TypedDict):
	entitlementId: int
	entitlementSource: str
	entitlementTag: str
	entitlementType: str
	grantDate: str
	groupName: str
	isConsumable: bool
	lastModifiedDate: str
	originPermissions: int
	pidUri: str
	productCatalog: str
	productId: str
	projectId: str
	status: str
	statusReasonCode: str
	terminationDate: str
	useCount: int
	version: int


class EntitlementContainer(TypedDict):
	entitlement: List[Entitlement]


class Entitlements(TypedDict):
	entitlements: EntitlementContainer


class Persona(TypedDict):
	dateCreated: str
	displayName: str
	isVisible: bool
	lastAuthenticated: str
	name: str
	namespaceName: Namespace
	personaId: int
	pidId: int
	showPersona: str
	status: str
	statusReasonCode: str


class PersonaContainer(TypedDict):
	persona: List[Persona]


class Personas(TypedDict):
	personas: PersonaContainer


class PersonaDetails(TypedDict):
	displayName: str
	extId: int
	lastAuthenticated: int
	personaId: int
	status: str


class PlatformInfoIds(TypedDict):
	nucleusAccountId: int
	originPersonaId: int
	originPersonaName: str


class PlatformExternalIds(TypedDict):
	psnAccountId: int
	steamAccountId: int
	switchId: str
	xblAccountId: int


class PlatformInfo(TypedDict):
	clientPlatform: str
	eaIds: PlatformInfoIds
	externalIds: PlatformExternalIds


class UserLoginInfo(TypedDict):
	accountId: int
	blazeId: int
	geoIpSucceeded: bool
	isFirstConsoleLogin: bool
	isFirstLogin: bool
	lastLoginDateTime: int
	personaDetails: PersonaDetails
	platformInfo: PlatformInfo
	previousAnonymousAccountId: int
	sessionKey: str


class BlazeAuthenticatedResponse(TypedDict):
	isAnonymous: bool
	isOfLegalContactAge: bool
	isUnderage: bool
	userLoginInfo: UserLoginInfo


class AuctionSynergyTier(TypedDict):
	id: int


class AuctionSynergy(TypedDict, total=False):
	synergyId: int
	tierList: List[AuctionSynergyTier]
	displayOrder: int
	inLineupCount: int
	isSynergyEnabled: bool
	iconImageHighResolution: str
	iconImageLowResolution: str
	upgradeSlotId: int
	onCardCount: int


class AuctionProgram(TypedDict, total=False):
	programId: int
	programName: str
	programDescription: str
	color: int
	revealVideo: str
	stampImage: str


class AuctionTeamRating(TypedDict):
	label: str
	value: int


class AuctionUIAttribute(TypedDict):
	attribute: str
	string: str


AuctionCardAttributeMap = Dict[str, Any]


class AuctionCardData(TypedDict):
	tdfid: int
	tdfclass: str
	value: AuctionCardAttributeMap


class AuctionCard(TypedDict, total=False):
	cardId: int
	cardInstanceId: int
	cardOwnerBlazeId: int
	condensedName: str
	firstName: str
	secondName: str
	cardState: str
	description: str
	longDescription: str
	discardValue: int
	cardValue: int
	tier: int
	teamId: int
	type: str
	program: AuctionProgram
	cardAssetType: str
	mainImage: str
	medianListingPrice: int
	minListingPrice: int
	maxListingPrice: int
	isTradeable: bool
	isAuctionable: bool
	isCollectable: bool
	isLimitedEdition: bool
	synergyList: List[AuctionSynergy]
	activeSynergyBoostList: List[Any]
	slotAbilityIdList: List[int]
	passivePlayerAbilities: List[int]
	teamRatingDataList: List[AuctionTeamRating]
	uIDataList: List[AuctionUIAttribute]
	cardData: AuctionCardData
	staticCardData: AuctionCardData


AuctionStatus = Literal[
	"AUCTIONSTATUS_ACTIVE",
	"AUCTIONSTATUS_ENDED",
	"AUCTIONSTATUS_EXPIRED",
	"AUCTIONSTATUS_CANCELLED",
]


class AuctionDetail(TypedDict, total=False):
	auctionId: int
	auctionStatus: AuctionStatus
	buyoutPrice: int
	currentBid: int
	nextBid: int
	numberOfBids: int
	postingTime: int
	secondsRemaining: int
	sellerId: int
	buyerId: int
	medianAuctionPrice: int
	minListingPrice: int
	maxListingPrice: int
	medianListingPrice: int
	card: AuctionCard


class AuctionResponseData(TypedDict, total=False):
	cacheTime: int
	captchaGuid: str
	captchaPrivacyMsg: str
	captchaPublicKey: str
	captchaTimeout: str
	captchaUrl: str
	uiErrorCode: int
	messageTitle: str
	message: str
	responseTime: int


class AuctionSearchValue(TypedDict):
	details: List[AuctionDetail]
	responseData: AuctionResponseData
	truncated: bool


class AuctionResponseInfo(TypedDict):
	tdfid: int
	tdfclass: str
	value: AuctionSearchValue


class AuctionSearchResponse(TypedDict):
	responseInfo: AuctionResponseInfo


__all__ = [
	"AUTH_SOURCE",
	"CLIENT_SECRET",
	"REDIRECT_URL",
	"CLIENT_ID",
	"MACHINE_KEY",
	"EA_LOGIN_URL",
	"TWO_DIGIT_YEAR",
	"YEAR",
	"SYSTEM_MAP",
	"NAMESPACES",
	"BLAZE_SERVICE",
	"BLAZE_SERVICE_TO_PATH",
	"BLAZE_PRODUCT_NAME",
	"AccountToken",
	"TokenInfo",
	"Entitlement",
	"EntitlementContainer",
	"Entitlements",
	"Persona",
	"PersonaContainer",
	"Personas",
	"PersonaDetails",
	"PlatformInfoIds",
	"PlatformExternalIds",
	"PlatformInfo",
	"UserLoginInfo",
	"BlazeAuthenticatedResponse",
	"Namespace",
	"AuctionSynergyTier",
	"AuctionSynergy",
	"AuctionProgram",
	"AuctionTeamRating",
	"AuctionUIAttribute",
	"AuctionCardAttributeMap",
	"AuctionCardData",
	"AuctionCard",
	"AuctionStatus",
	"AuctionDetail",
	"AuctionResponseData",
	"AuctionSearchValue",
	"AuctionResponseInfo",
	"AuctionSearchResponse",
]
