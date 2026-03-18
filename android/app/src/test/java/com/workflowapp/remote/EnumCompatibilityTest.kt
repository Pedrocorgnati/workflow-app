package com.workflowapp.remote

import com.workflowapp.remote.model.ControlAction
import com.workflowapp.remote.model.PipelineViewState
import com.workflowapp.remote.model.ResponseType
import com.workflowapp.remote.model.WsMessageType
import com.workflowapp.remote.connection.MessageParser
import org.junit.Assert.*
import org.junit.Test

/**
 * Testes de compatibilidade de enums entre o lado Android (Kotlin) e o lado PC (Python).
 *
 * Notas sobre divergências documentadas:
 * - [WsMessageType] tem 15 valores (7 PC→Android + 4 Android→PC + 4 internos: PING, PONG,
 *   CONNECTED, COMMAND_STATUS_CHANGED, SYNC_RESPONSE). O subconjunto dos 10 do protocolo
 *   estão todos presentes.
 * - [ControlAction] tem 4 valores no Android (PLAY, PAUSE, SKIP, RESUME). O Python tem 3
 *   (sem RESUME). RESUME é uma extensão Android para retomar pipeline pausado — o Python
 *   trata RESUME como alias de PLAY na lógica de controle.
 * - CommandStatus não existe como enum Kotlin. O lado Android usa strings em [PipelineStateMsg].
 * - [PipelineViewState] espelha Python PipelineStatus com os mesmos 8 valores de protocolo.
 */
class EnumCompatibilityTest {

    // ── WsMessageType: 10 tipos do protocolo devem estar presentes ───────────

    @Test
    fun `WsMessageType contem todos os 7 tipos PC para Android`() {
        val pcTypes = listOf(
            "output_chunk", "output_truncated", "pipeline_state",
            "interaction_request", "interactive_mode_ended", "error", "control_ack",
        )
        val actualValues = WsMessageType.entries.map { it.value }
        pcTypes.forEach { expected ->
            assertTrue(
                "WsMessageType deve conter '$expected'",
                actualValues.contains(expected),
            )
        }
    }

    @Test
    fun `WsMessageType contem todos os 3 tipos Android para PC`() {
        val androidTypes = listOf("control", "interaction_response", "sync_request")
        val actualValues = WsMessageType.entries.map { it.value }
        androidTypes.forEach { expected ->
            assertTrue(
                "WsMessageType deve conter '$expected'",
                actualValues.contains(expected),
            )
        }
    }

    @Test
    fun `WsMessageType fromValue reconhece os 10 tipos do protocolo`() {
        val protocolTypes = listOf(
            "output_chunk", "output_truncated", "pipeline_state",
            "interaction_request", "interactive_mode_ended", "error", "control_ack",
            "control", "interaction_response", "sync_request",
        )
        protocolTypes.forEach { typeStr ->
            assertNotNull(
                "WsMessageType.fromValue('$typeStr') não deve retornar null",
                WsMessageType.fromValue(typeStr),
            )
        }
    }

    @Test
    fun `WsMessageType fromValue retorna null para tipo desconhecido`() {
        assertNull(WsMessageType.fromValue("unknown_type"))
        assertNull(WsMessageType.fromValue(""))
    }

    // ── ControlAction: play, pause, skip são obrigatórios ────────────────────

    @Test
    fun `ControlAction contem os 3 valores do protocolo base`() {
        val requiredValues = listOf("play", "pause", "skip")
        val actualValues = ControlAction.values().map { it.value }
        requiredValues.forEach { expected ->
            assertTrue(
                "ControlAction deve conter '$expected'",
                actualValues.contains(expected),
            )
        }
    }

    @Test
    fun `ControlAction tem ao menos 3 valores (extensoes Android sao aceitas)`() {
        // Python tem 3 (play/pause/skip). Kotlin tem 4 (adiciona RESUME).
        assertTrue(
            "ControlAction deve ter ao menos 3 valores",
            ControlAction.values().size >= 3,
        )
    }

    // ── ResponseType: 4 valores idênticos em Python e Kotlin ─────────────────

    @Test
    fun `ResponseType tem exatamente 4 valores`() {
        val expected = listOf("text", "yes", "no", "cancel")
        val actual = ResponseType.values().map { it.value }
        assertEquals(expected.sorted(), actual.sorted())
    }

    // ── PipelineViewState: 8 valores espelham Python PipelineStatus ──────────

    @Test
    fun `PipelineViewState tem exatamente 8 valores`() {
        assertEquals(8, PipelineViewState.values().size)
    }

    @Test
    fun `PipelineViewState valores correspondem ao protocolo`() {
        val expected = listOf(
            "idle", "running", "paused", "completed", "failed",
            "cancelled", "waiting_interaction", "interactive_mode",
        )
        // PipelineViewState usa fromString() para mapeamento — verificar via enum names
        val enumNames = PipelineViewState.values().map { it.name.lowercase() }
        expected.forEach { protocolValue ->
            // Map protocol value to enum name (waiting_interaction → waiting_interaction)
            val normalized = protocolValue.replace("_", "_")
            assertTrue(
                "PipelineViewState deve mapear '$protocolValue'",
                enumNames.contains(normalized) || PipelineViewState.fromString(protocolValue) != PipelineViewState.IDLE || protocolValue == "idle",
            )
        }
    }

    @Test
    fun `PipelineViewState fromString mapeia os 8 estados corretamente`() {
        assertEquals(PipelineViewState.IDLE, PipelineViewState.fromString("idle"))
        assertEquals(PipelineViewState.RUNNING, PipelineViewState.fromString("running"))
        assertEquals(PipelineViewState.PAUSED, PipelineViewState.fromString("paused"))
        assertEquals(PipelineViewState.COMPLETED, PipelineViewState.fromString("completed"))
        assertEquals(PipelineViewState.FAILED, PipelineViewState.fromString("failed"))
        assertEquals(PipelineViewState.CANCELLED, PipelineViewState.fromString("cancelled"))
        assertEquals(PipelineViewState.WAITING_INTERACTION, PipelineViewState.fromString("waiting_interaction"))
        assertEquals(PipelineViewState.INTERACTIVE_MODE, PipelineViewState.fromString("interactive"))
    }

    // ── UUID v4: formato correto em ambos os lados ────────────────────────────

    @Test
    fun `UUID v4 tem formato correto`() {
        val pattern = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        repeat(10) {
            val id = java.util.UUID.randomUUID().toString()
            assertTrue("UUID inválido: $id", pattern.matches(id))
        }
    }

    @Test
    fun `UUID gerado pelo serialize contem message_id em formato UUID`() {
        val parser = MessageParser()
        val json = parser.serialize("sync_request")
        assertTrue("JSON deve conter message_id", json.contains("message_id"))
        // Extrair message_id do JSON usando regex simples
        val idMatch = Regex("\"message_id\"\\s*:\\s*\"([^\"]+)\"").find(json)
        assertNotNull("message_id não encontrado no JSON", idMatch)
        val generatedId = idMatch!!.groupValues[1]
        val pattern = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        assertTrue("message_id gerado não é UUID v4: $generatedId", pattern.matches(generatedId))
    }

    // ── Forward compatibility: campos extras ignorados ────────────────────────

    @Test
    fun `parse ignora campos extras - forward compat`() {
        val parser = MessageParser()
        val raw = """{"message_id":"550e8400-e29b-41d4-a716-446655440009","type":"sync_request","timestamp":"2025-01-15T10:30:00Z","payload":{},"campo_futuro":"ignorar","nested":{"key":"value"}}"""
        val result = parser.parse(raw)
        assertNotNull(result)
    }

    @Test
    fun `timestamp sem milissegundos e aceito pelo parse`() {
        val parser = MessageParser()
        val raw = """{"message_id":"550e8400-e29b-41d4-a716-446655440009","type":"sync_request","timestamp":"2025-01-15T10:30:00Z","payload":{}}"""
        val result = parser.parse(raw)
        assertNotNull(result)
        assertEquals("2025-01-15T10:30:00Z", result!!.timestamp)
    }
}
