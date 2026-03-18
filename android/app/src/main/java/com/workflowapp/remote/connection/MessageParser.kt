package com.workflowapp.remote.connection

import com.workflowapp.remote.model.CommandItem
import com.workflowapp.remote.model.ControlAckMsg
import com.workflowapp.remote.model.ErrorMsg
import com.workflowapp.remote.model.InteractionRequestMsg
import com.workflowapp.remote.model.InteractiveModeEndedMsg
import com.workflowapp.remote.model.OutputChunkMsg
import com.workflowapp.remote.model.OutputTruncatedMsg
import com.workflowapp.remote.model.PipelineStateMsg
import com.workflowapp.remote.model.RemoteMessage
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import com.workflowapp.remote.util.RemoteLogger
import java.util.UUID

/**
 * MessageParser — parses inbound WebSocket messages into typed [RemoteMessage] objects
 * and serializes outbound commands to JSON envelopes.
 *
 * **Inbound path:** raw JSON → [parseMessage] → [RemoteMessage]?
 * - Validates type against [ACCEPTED_TYPES] whitelist
 * - Deduplicates by [message_id] (FIFO window of [MAX_SEEN_IDS] = 1000)
 * - Returns null for unknown types, duplicates, missing fields, or malformed JSON
 *
 * **Outbound path:** (type, payload) → [serialize] → JSON envelope String
 * - Adds [message_id] (UUID v4) and [timestamp] (ISO-8601)
 *
 * **Backward-compatible path:** [parse] returns [WsEnvelope] for [WebSocketClient]
 * integration, keeping the existing connection layer unchanged.
 */
class MessageParser {

    // ── Whitelist of accepted inbound message types ──────────────────────────

    private val ACCEPTED_TYPES = setOf(
        "pipeline_state",
        "output_chunk",
        "output_truncated",
        "interaction_request",
        "interactive_mode_ended",
        "error",
        "control_ack",
    )

    // ── Deduplication (FIFO, max 1000 entries) ───────────────────────────────

    private val seenIds = ArrayDeque<String>()

    /** Exposed for unit tests — do NOT use in production code. */
    internal val seenIdsForTest: ArrayDeque<String> get() = seenIds

    // ── Inbound: raw JSON → RemoteMessage (typed, kotlinx.serialization) ─────

    /**
     * Parse a raw WebSocket text frame into a [RemoteMessage].
     *
     * Returns null if:
     * - JSON is malformed
     * - [type] field is missing or not in [ACCEPTED_TYPES]
     * - [message_id] field is missing
     * - message_id was already processed (dedup)
     * - A required payload field is missing for the given type
     */
    fun parseMessage(json: String): RemoteMessage? = try {
        parseMessageInternal(json)
    } catch (e: Exception) {
        RemoteLogger.e("Failed to parse message: ${e.message}")
        null
    }

    private fun parseMessageInternal(json: String): RemoteMessage? {
        val root = Json.parseToJsonElement(json).jsonObject

        val type = root["type"]?.jsonPrimitive?.contentOrNull
        val messageId = root["message_id"]?.jsonPrimitive?.contentOrNull

        if (type == null) {
            RemoteLogger.w("Message missing 'type' field — discarding")
            return null
        }
        if (messageId == null) {
            RemoteLogger.w("Message missing 'message_id' field — discarding")
            return null
        }
        if (type !in ACCEPTED_TYPES) {
            RemoteLogger.w("Unknown message type '$type' — discarding")
            return null
        }
        if (isDuplicate(messageId)) {
            RemoteLogger.d("Duplicate message_id '$messageId' — discarding")
            return null
        }

        val payload = root["payload"]?.jsonObject
        return routeByType(type, messageId, payload)
    }

    /**
     * Convenience overload: parse a message from an already-extracted [WsEnvelope].
     * Avoids re-parsing the JSON — reconstructs a minimal JSON object from envelope fields.
     */
    fun parseMessage(envelope: WsEnvelope): RemoteMessage? {
        val type = envelope.type
        val messageId = envelope.messageId.takeIf { it.isNotEmpty() } ?: run {
            RemoteLogger.w("Envelope missing message_id — discarding")
            return null
        }
        if (type !in ACCEPTED_TYPES) {
            RemoteLogger.w("Unknown message type '$type' — discarding")
            return null
        }
        if (isDuplicate(messageId)) {
            RemoteLogger.d("Duplicate message_id '$messageId' — discarding")
            return null
        }
        val payload = try {
            Json.parseToJsonElement(envelope.payloadRaw).jsonObject
        } catch (e: Exception) {
            null
        }
        return routeByType(type, messageId, payload)
    }

    private fun isDuplicate(id: String): Boolean {
        if (seenIds.contains(id)) return true
        seenIds.addFirst(id)
        if (seenIds.size > MAX_SEEN_IDS) seenIds.removeLast()
        return false
    }

    private fun routeByType(
        type: String,
        messageId: String,
        payload: kotlinx.serialization.json.JsonObject?,
    ): RemoteMessage? = when (type) {

        "pipeline_state" -> {
            val status = payload?.get("status")?.jsonPrimitive?.contentOrNull ?: run {
                RemoteLogger.w("pipeline_state missing 'status'")
                return null
            }
            val commands = payload["commands"]?.jsonArray?.mapNotNull { elem ->
                val obj = elem.jsonObject
                val index = obj["index"]?.jsonPrimitive?.intOrNull ?: return@mapNotNull null
                val name = obj["name"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null
                val cmdStatus = obj["status"]?.jsonPrimitive?.contentOrNull ?: "pending"
                CommandItem(index, name, cmdStatus)
            } ?: emptyList()
            PipelineStateMsg(messageId, commands, status)
        }

        "output_chunk" -> {
            val lines = payload?.get("lines")?.jsonArray?.map {
                it.jsonPrimitive.content
            } ?: emptyList()
            OutputChunkMsg(messageId, lines)
        }

        "output_truncated" -> {
            val linesOmitted = payload?.get("lines_omitted")?.jsonPrimitive?.intOrNull ?: 0
            OutputTruncatedMsg(messageId, linesOmitted)
        }

        "interaction_request" -> {
            val prompt = payload?.get("prompt")?.jsonPrimitive?.contentOrNull ?: run {
                RemoteLogger.w("interaction_request missing 'prompt'")
                return null
            }
            val interType = payload["type"]?.jsonPrimitive?.contentOrNull ?: "text"
            val options = payload["options"]?.jsonArray?.map {
                it.jsonPrimitive.content
            } ?: emptyList()
            InteractionRequestMsg(messageId, prompt, interType, options)
        }

        "interactive_mode_ended" -> InteractiveModeEndedMsg(messageId)

        "error" -> {
            val error = payload?.get("message")?.jsonPrimitive?.contentOrNull ?: "Unknown error"
            ErrorMsg(messageId, error)
        }

        "control_ack" -> {
            val action = payload?.get("action")?.jsonPrimitive?.contentOrNull ?: ""
            val accepted = payload?.get("accepted")?.jsonPrimitive?.booleanOrNull ?: false
            ControlAckMsg(messageId, action, accepted)
        }

        else -> null  // Already filtered by whitelist — should never reach here
    }

    // ── Inbound: raw JSON → WsEnvelope (backward-compatible, for WebSocketClient) ──

    /**
     * Parse a raw WebSocket text frame into a [WsEnvelope].
     *
     * Returns null if the JSON is malformed or mandatory fields are missing.
     * Unknown [type] values are returned as-is so the caller can log and ignore them.
     *
     * This method is kept for [WebSocketClient] backward compatibility.
     * New code should use [parseMessage] for typed [RemoteMessage] results.
     */
    fun parse(raw: String): WsEnvelope? = try {
        val root = Json.parseToJsonElement(raw).jsonObject
        val messageId = root["message_id"]?.jsonPrimitive?.contentOrNull ?: ""
        val type = root["type"]?.jsonPrimitive?.contentOrNull ?: ""
        val timestamp = root["timestamp"]?.jsonPrimitive?.contentOrNull ?: ""
        val payloadRaw = root["payload"]?.jsonObject?.toString() ?: "{}"
        WsEnvelope(
            messageId = messageId,
            type = type,
            timestamp = timestamp,
            payloadRaw = payloadRaw,
        )
    } catch (e: Exception) {
        RemoteLogger.w("Failed to parse WebSocket message: ${e.message}")
        null
    }

    // ── Outbound: (type, payload) → JSON envelope ─────────────────────────────

    /**
     * Serialize a (type, payload) pair into a JSON envelope String ready to send.
     * Adds a random [message_id] and the current ISO-8601 UTC timestamp.
     */
    fun serialize(type: String, payload: JsonObject): String {
        val envelope = buildJsonObject {
            put("message_id", UUID.randomUUID().toString())
            put("type", type)
            put("timestamp", java.time.Instant.now().toString())
            put("payload", payload)
        }
        return envelope.toString()
    }

    /** Serialize with a Map payload — converts each value to its string representation. */
    fun serialize(type: String, payload: Map<String, Any>): String {
        val payloadObj = buildJsonObject {
            payload.forEach { (k, v) -> put(k, v.toString()) }
        }
        return serialize(type, payloadObj)
    }

    /** Convenience overload that accepts an empty payload. */
    fun serialize(type: String): String = serialize(type, buildJsonObject {})

    companion object {
        private const val MAX_SEEN_IDS = 1000
    }
}

// ── WsEnvelope ───────────────────────────────────────────────────────────────

/**
 * Parsed WebSocket envelope (backward-compatible with [WebSocketClient]).
 *
 * [payloadRaw] is a JSON string rather than a typed object so the ViewModel
 * can parse each payload type independently.
 */
data class WsEnvelope(
    val messageId:  String,
    val type:       String,
    val timestamp:  String,
    val payloadRaw: String,
)
