package com.workflowapp.remote

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.viewmodel.compose.viewModel
import com.workflowapp.remote.ui.WorkflowScreen
import com.workflowapp.remote.ui.theme.WorkflowAppTheme
import com.workflowapp.remote.viewmodel.PipelineViewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Prevent screen capture / Recent Apps thumbnail for security
        window.setFlags(
            WindowManager.LayoutParams.FLAG_SECURE,
            WindowManager.LayoutParams.FLAG_SECURE,
        )

        enableEdgeToEdge()

        setContent {
            WorkflowAppTheme {
                WorkflowScreen(viewModel = viewModel(factory = PipelineViewModel.Factory))
            }
        }
    }
}
