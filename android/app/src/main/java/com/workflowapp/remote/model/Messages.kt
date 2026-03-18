package com.workflowapp.remote.model

/**
 * Typed message hierarchy for all messages received from the PC via WebSocket.
 *
 * The sealed class guarantees exhaustive `when` expressions at compile time.
 * All subclasses carry [messageId] for deduplication in [com.workflowapp.remote.connection.MessageParser].
 */
sealed class RemoteMessage {
    abstract val messageId: String
}

/** Full pipeline state snapshot — sent by server on connection/sync and after state changes. */
data class PipelineStateMsg(
    override val messageId: String,
    val commandQueue: List<CommandItem>,
    val status: String,
) : RemoteMessage()

/** Streamed output lines from the running pipeline. */
data class OutputChunkMsg(
    override val messageId: String,
    val lines: List<String>,
) : RemoteMessage()

/** Notification that output was truncated to avoid bandwidth overload. */
data class OutputTruncatedMsg(
    override val messageId: String,
    val linesOmitted: Int,
) : RemoteMessage()

/** Server requests user input before pipeline can continue. */
data class InteractionRequestMsg(
    override val messageId: String,
    val prompt: String,
    val type: String,
    val options: List<String>,
) : RemoteMessage()

/** Server signals that interactive mode has ended (user responded or timed out). */
data class InteractiveModeEndedMsg(
    override val messageId: String,
) : RemoteMessage()

/** Server-side error notification. */
data class ErrorMsg(
    override val messageId: String,
    val error: String,
) : RemoteMessage()

/** Acknowledgement of a control command sent by the client. */
data class ControlAckMsg(
    override val messageId: String,
    val action: String,
    val accepted: Boolean,
) : RemoteMessage()

// ── Outbound enums ───────────────────────────────────────────────────────────

/**
 * Control actions dispatched to the PC pipeline.
 *
 * Note: PLAY is sent when the pipeline is IDLE; RESUME is sent when the pipeline is PAUSED.
 * The ViewModel handles this substitution automatically in [sendControl()].
 * Python ALLOWED_CONTROL_ACTIONS = {"play", "pause", "skip", "resume"}.
 */
enum class ControlAction(val value: String) {
    PLAY("play"),
    PAUSE("pause"),
    SKIP("skip"),
    RESUME("resume"),
}

/** Response types for [InteractionRequestMsg] answers. */
enum class ResponseType(val value: String) {
    TEXT("text"),
    YES("yes"),
    NO("no"),
    CANCEL("cancel"),
}
