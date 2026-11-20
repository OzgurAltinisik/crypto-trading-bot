import React from "react"
import ReactDOM from "react-dom/client"

import App from "@/App"
import "@/index.css"
import { ManagePage, PrivacyPage } from "@/pages"

// tiny router: the server returns index.html for these paths
const path = location.pathname.replace(/\/+$/, "")
const Page = path === "/abonelik" ? ManagePage : path === "/gizlilik" ? PrivacyPage : App

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>,
)
