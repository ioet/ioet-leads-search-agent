"""ioet BambooHR skill custom-field aliases (level 1–5 per field).

Bamboo stores each skill as its own custom field (e.g. customAWS=4).
HR / PII fields from the same custom namespace are excluded.
Override via env BAMBOOHR_SKILL_FIELDS (comma-separated aliases).
"""

from __future__ import annotations

import os

# Fields that appear alongside skills in Bamboo but are not tech skills.
_NON_SKILL_CUSTOM_FIELDS = frozenset(
    {
        "customBBAN",
        "customBeneficiaryName",
        "customCEDULA",
        "customNationalInsurance#",
        "customNextReviewDate1",
        "customCityofBirth",
        "customProposedSalary",
        "customRUC",
        "customSWIFT/BIC",
        "customClient",
        "customGitHubID",
        "customRank",
        "customReviewStatus",
        "customGeo",
    }
)

# Curated from ioet Bamboo employee custom fields (levels 1–5).
DEFAULT_SKILL_FIELDS: tuple[str, ...] = tuple(
    field
    for field in (
        "customNETCoreNET5",
        "customNETFramework",
        "customAPL",
        "customASPNET",
        "customASPNETCore",
        "customAWS",
        "customAdobeTools",
        "customAndroid",
        "customAngular",
        "customAngularjs",
        "customAnsible",
        "customApacheSpark",
        "customAppium",
        "customAssembly",
        "customBSD",
        "customBashShell",
        "customBitbucket",
        "customBusinessAnalysis",
        "customC",
        "customC1",
        "customC2",
        "customCOBOL",
        "customCassandra",
        "customChef",
        "customClojure",
        "customConfluence",
        "customContentful",
        "customCordova",
        "customCouchbase",
        "customCrystal",
        "customCypress",
        "customDart",
        "customDataAnalysis",
        "customDataEngineering",
        "customDataScience",
        "customDatabricks",
        "customDatadog",
        "customDeepLearning",
        "customDelphi",
        "customDeno",
        "customDigitalOcean",
        "customDjango",
        "customDocker",
        "customDrupal",
        "customDynamoDB",
        "customElasticsearch",
        "customElixir",
        "customEnglishLevel1",
        "customErlang",
        "customExpress",
        "customF",
        "customFastAPI",
        "customFigma",
        "customFirebase",
        "customFlask",
        "customFlow",
        "customFlutter",
        "customFortifyOnDemand",
        "customFramer",
        "customGatling",
        "customGatsby",
        "customGenerativeAI",
        "customGit",
        "customGitHub",
        "customGitLab",
        "customGo",
        "customGoogleCloudPlatform",
        "customGroovy",
        "customHTMLCSS",
        "customHadoop",
        "customHaskell",
        "customHeroku",
        "customIBMCloudorWatson",
        "customIBMDB2",
        "customIllustrator",
        "customJava",
        "customJavaScript",
        "customJest",
        "customJira",
        "customJmeter",
        "customJulia",
        "customK6",
        "customKatalonstudio",
        "customKeras",
        "customKotlin",
        "customKubernetes",
        "customLISP",
        "customLaravel",
        "customLinuxbased",
        "customLoadRunner",
        "customMacOS",
        "customMachineLearning",
        "customMariaDB",
        "customMatlab",
        "customMicrosoftAzure",
        "customMicrosoftSQLServer",
        "customMiro",
        "customMondaycom",
        "customMongoDB",
        "customMySQL",
        "customNestjs",
        "customNetworking",
        "customNextjs",
        "customNodejs",
        "customNotion",
        "customNumPy",
        "customObjectiveC",
        "customOracle",
        "customOracleCloudInfrastructure",
        "customPHP",
        "customPandas",
        "customPerl",
        "customPhotoshop",
        "customPlaywright",
        "customPostgreSQL",
        "customPostman",
        "customPowerShell",
        "customProjectManagement",
        "customPulumi",
        "customPuppet",
        "customPython",
        "customQt",
        "customR",
        "customRPA",
        "customReactNative",
        "customReactjs",
        "customRedis",
        "customRobotFramework",
        "customRuby",
        "customRubyonRails",
        "customRust",
        "customSQL",
        "customSQLite",
        "customScala",
        "customSelenium",
        "customSentry",
        "customShopify",
        "customSoapui",
        "customSpring",
        "customSpringBoot",
        "customSvelte",
        "customSwift",
        "customSymfony",
        "customTensorFlow",
        "customTerraform",
        "customTorchPyTorch",
        "customTypeScript",
        "customUnity3D",
        "customUnrealEngine",
        "customVBA",
        "customVuejs",
        "customW3Cvalidator",
        "customWindows",
        "customWindowsSubsystemforLinuxWSL",
        "customXamarin",
        "customYarn",
        "customiOS",
        "customjQuery",
    )
    if field not in _NON_SKILL_CUSTOM_FIELDS
)


def skill_field_aliases() -> list[str]:
    """Skill custom-field aliases: env override or ioet defaults."""
    raw = os.environ.get("BAMBOOHR_SKILL_FIELDS", "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return list(DEFAULT_SKILL_FIELDS)


def display_skill_name(field_alias: str) -> str:
    """customAWS → AWS; customNETCoreNET5 → NETCoreNET5."""
    name = field_alias.strip()
    if name.lower().startswith("custom"):
        name = name[6:]
    return name or field_alias


def skill_level(value: object, *, min_level: int = 1, max_level: int = 5) -> int | None:
    """Return int level if value is a number in [min_level, max_level]."""
    if value is None or value == "":
        return None
    try:
        level = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if min_level <= level <= max_level:
        return level
    return None


def skills_from_level_fields(
    detail: dict,
    field_aliases: list[str],
    *,
    min_level: int | None = None,
    max_level: int | None = None,
) -> list[str]:
    """Build skills[] from Bamboo custom fields whose values are levels 1–5."""
    low = min_level if min_level is not None else int(os.environ.get("BAMBOOHR_SKILL_LEVEL_MIN", "1"))
    high = max_level if max_level is not None else int(os.environ.get("BAMBOOHR_SKILL_LEVEL_MAX", "5"))
    skills: list[str] = []
    seen: set[str] = set()
    for alias in field_aliases:
        level = skill_level(detail.get(alias), min_level=low, max_level=high)
        if level is None:
            continue
        label = display_skill_name(alias)
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        skills.append(label)
    return skills


def chunked(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]
