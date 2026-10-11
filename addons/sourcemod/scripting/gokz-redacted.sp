#include <sourcemod>
#include <sdktools>

#pragma newdecls required
#pragma semicolon 1

public Plugin myinfo =
{
    name        = "GOKZ Redacted",
    author      = "jvnipers",
    description = "Covers explicit images on maps with black panels",
    version     = "1.0.1",
    url         = "https://github.com/FemboyKZ/gokz-redacted"
};

// Covers: configs/gokz-redacted/<map>.cfg, written by scripts/bspcover.py.
// Models: scripts/covermodel.py.

// SIZE in covermodel.py
#define COVER_SIZE      32.0
// Units off the surface. Less: "solid" covers flicker sooner. More: noclip can peek behind.
#define COVER_OFFSET    0.25
// Entity angles reach clients cut down to steps of this.
#define ANGLE_STEP      (360.0 / 8192.0)
// The server crashes at 2048.
#define MAX_USED_EDICTS 1900

// ASPECTS in bspcover.py
static const int  coverAspects[] = { 1, 2, 4, 8, 16, 32, 64 };
// MATERIALS in covermodel.py
static const char coverKinds[][] = { "cover", "late", "solid" };

KeyValues         covers;
ArrayList         spawned;

// =====[ PLUGIN EVENTS ]=====
public void OnPluginStart()
{
    spawned = new ArrayList();
    HookEvent("round_start", OnRoundStart, EventHookMode_PostNoCopy);
}

public void OnPluginEnd()
{
    RemoveCovers();
}

public void OnMapStart()
{
    delete covers;

    char map[PLATFORM_MAX_PATH];
    GetCurrentMap(map, sizeof(map));
    GetMapDisplayName(map, map, sizeof(map));

    char path[PLATFORM_MAX_PATH];
    BuildPath(Path_SM, path, sizeof(path), "configs/gokz-redacted/%s.cfg", map);
    if (!FileExists(path))
    {
        return;
    }

    covers = new KeyValues("covers");
    if (!covers.ImportFromFile(path))
    {
        LogError("Failed to read %s", path);
        delete covers;
        return;
    }

    for (int kind = 0; kind < sizeof(coverKinds); kind++)
    {
        char file[PLATFORM_MAX_PATH];
        FormatEx(file, sizeof(file), "materials/gokz-redacted/%s.vmt", coverKinds[kind]);
        AddFileToDownloadsTable(file);
        for (int i = 0; i < sizeof(coverAspects); i++)
        {
            FormatEx(file, sizeof(file), "models/gokz-redacted/%s%d.mdl", coverKinds[kind], coverAspects[i]);
            PrecacheModel(file, true);
            AddFileToDownloadsTable(file);
            FormatEx(file, sizeof(file), "models/gokz-redacted/%s%d.vvd", coverKinds[kind], coverAspects[i]);
            AddFileToDownloadsTable(file);
            FormatEx(file, sizeof(file), "models/gokz-redacted/%s%d.dx90.vtx", coverKinds[kind], coverAspects[i]);
            AddFileToDownloadsTable(file);
        }
    }

    SpawnCovers();
}

// A round restart removes spawned entities.
public void OnRoundStart(Event event, const char[] name, bool dontBroadcast)
{
    SpawnCovers();
}

// =====[ PRIVATE ]=====

static void RemoveCovers()
{
    for (int i = 0; i < spawned.Length; i++)
    {
        int entity = EntRefToEntIndex(spawned.Get(i));
        if (entity != INVALID_ENT_REFERENCE)
        {
            RemoveEntity(entity);
        }
    }
    spawned.Clear();
}

static void SpawnCovers()
{
    RemoveCovers();
    if (covers == null)
    {
        return;
    }

    covers.Rewind();
    if (!covers.GotoFirstSubKey())
    {
        return;
    }

    do
    {
        int parent   = -1;
        int hammerID = covers.GetNum("parent");
        if (hammerID != 0)
        {
            parent = FindEntityByHammerID(hammerID);
            // The surface went with its entity.
            if (parent == -1)
            {
                continue;
            }
        }

        float origin[3], angles[3], forwards[3], right[3];
        covers.GetVector("origin", origin);
        covers.GetVector("angles", angles);
        float width  = covers.GetFloat("width");
        float height = covers.GetFloat("height");
        GetAngleVectors(angles, forwards, right, NULL_VECTOR);

        // Sent mid-step so the client's cut lands on a known angle.
        // Any tilt left over sinks one end into the surface, so lift by that much.
        float sent[3], seen[3], seenForwards[3];
        for (int axis = 0; axis < 3; axis++)
        {
            int steps  = RoundToNearest(angles[axis] / ANGLE_STEP);
            seen[axis] = steps * ANGLE_STEP;
            sent[axis] = (steps + 0.5) * ANGLE_STEP;
        }
        GetAngleVectors(seen, seenForwards, NULL_VECTOR, NULL_VECTOR);
        float tilt   = GetVectorDistance(forwards, seenForwards);

        // Widest model that fits.
        int   aspect = coverAspects[0];
        for (int i = 1; i < sizeof(coverAspects); i++)
        {
            if (coverAspects[i] * height <= width + 0.01)
            {
                aspect = coverAspects[i];
            }
        }

        char kind[8];
        covers.GetString("kind", kind, sizeof(kind), coverKinds[0]);

        float modelWidth = aspect * height;
        int   count      = RoundToCeil(width / modelWidth - 0.001);
        float reach      = SquareRoot(modelWidth * modelWidth + height * height) / 2.0;
        for (int i = 0; i < count; i++)
        {
            // Outer copies sit flush with the ends, the rest overlap.
            float along = count == 1 ? 0.0 : (width - modelWidth) * (float(i) / (count - 1) - 0.5);
            float position[3];
            for (int axis = 0; axis < 3; axis++)
            {
                position[axis] = origin[axis] + forwards[axis] * (COVER_OFFSET + reach * tilt) + right[axis] * along;
            }

            if (GetEntityCount() >= MAX_USED_EDICTS)
            {
                LogError("Out of edicts, some covers are missing");
                return;
            }
            SpawnCover(position, sent, kind, aspect, height / COVER_SIZE, parent);
        }
    }
    while (covers.GotoNextKey());
}

static void SpawnCover(const float position[3], const float angles[3], const char[] kind, int aspect, float scale, int parent)
{
    char model[PLATFORM_MAX_PATH];
    FormatEx(model, sizeof(model), "models/gokz-redacted/%s%d.mdl", kind, aspect);

    int entity = CreateEntityByName("prop_dynamic_override");
    DispatchKeyValue(entity, "model", model);
    DispatchKeyValue(entity, "solid", "0");
    DispatchKeyValue(entity, "disableshadows", "1");
    DispatchKeyValueFloat(entity, "modelscale", scale);
    DispatchSpawn(entity);
    TeleportEntity(entity, position, angles, NULL_VECTOR);

    if (parent != -1)
    {
        SetVariantString("!activator");
        AcceptEntityInput(entity, "SetParent", parent);
    }

    // Else the picture flashes before the cover arrives. Spawn and SetParent reset this.
    SetEdictFlags(entity, GetEdictFlags(entity) | FL_EDICT_ALWAYS);

    spawned.Push(EntIndexToEntRef(entity));
}

static int FindEntityByHammerID(int hammerID)
{
    for (int entity = MaxClients + 1; entity < GetMaxEntities(); entity++)
    {
        if (IsValidEntity(entity) && GetEntProp(entity, Prop_Data, "m_iHammerID") == hammerID)
        {
            return entity;
        }
    }
    return -1;
}
