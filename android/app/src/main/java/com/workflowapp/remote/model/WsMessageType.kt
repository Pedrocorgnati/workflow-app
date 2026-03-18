package com.workflowapp.remote.model

/**
 * WebSocket message types — mirror of Python MessageType enum.
 * All values are lowercase strings matching the "type" field in WsEnvelope.
 *
 * Android-side outbound (mobile → PC): CONTROL, INTERACTION_RESPONSE, SYNC_REQUEST, PONG
 * PC-side inbound (PC → mobile): all remaining types
 */
enum class WsMessageType(val value: String) {
    // PC → Mobile
    OUTPUT_CHUNK("output_chunk"),
    OUTPUT_TRUNCATED("output_truncated"),
    PIPELINE_STATE("pipeline_state"),
    INTERACTION_REQUEST("interaction_request"),
    INTERACTIVE_MODE_ENDED("interactive_mode_ended"),
    COMMAND_STATUS_CHANGED("command_status_changed"),
    CONTROL_ACK("control_ack"),
    ERROR("error"),
    CONNECTED("connected"),
    PING("ping"),
    SYNC_RESPONSE("sync_response"),

    // Mobile → PC
    CONTROL("control"),
    INTERACTION_RESPONSE("interaction_response"),
    SYNC_REQUEST("sync_request"),
    PONG("pong"),
    ;

    companion object {
        fun fromValue(value: String): WsMessageType? =
            entries.firstOrNull { it.value == value }

        /** Message types that originate from Android (outbound). */
        val ANDROID_OUTBOUND: Set<WsMessageType> = setOf(
            CONTROL, INTERACTION_RESPONSE, SYNC_REQUEST, PONG,
        )

        /** Message types that originate from the PC (inbound). */
        val PC_INBOUND: Set<WsMessageType> = entries.toSet() - ANDROID_OUTBOUND
    }
}
