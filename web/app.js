import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth, onAuthStateChanged, signInWithEmailAndPassword, signOut, getIdTokenResult, getIdToken,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";
import {
  getFirestore, collection, doc, addDoc, updateDoc, deleteDoc, onSnapshot, query, where, orderBy,
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js";

const firebaseConfig = {
  projectId: "meii-rnd",
  appId: "1:795409810940:web:e732a86af3dc408dd2de79",
  storageBucket: "meii-rnd.firebasestorage.app",
  apiKey: "AIzaSyDob4OqSVTa4V5f_T8mKsttwW1IeTa71RU",
  authDomain: "meii-rnd.firebaseapp.com",
  messagingSenderId: "795409810940",
};

const BACKEND_URL = "https://mehul-orders.onrender.com";
const CUSTOMER_EMAIL_DOMAIN = "mehulelectro.local";
const STATUS_OPTIONS = ["received", "quoted", "in_progress", "dispatched", "completed", "cancelled"];

const fbApp = initializeApp(firebaseConfig);
const auth = getAuth(fbApp);
const db = getFirestore(fbApp);

const loginView = document.getElementById("loginView");
const appView = document.getElementById("appView");
const page = document.getElementById("page");
const navLinks = document.getElementById("navLinks");

let currentRole = null;
let currentUid = null;
let unsubscribers = [];

function clearListeners() {
  unsubscribers.forEach((u) => u());
  unsubscribers = [];
}

function statusLabel(s) {
  return s.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
}

async function adminFetch(path, method, body) {
  const token = await getIdToken(auth.currentUser);
  const res = await fetch(BACKEND_URL + path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// ---------- auth ----------

document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("loginError");
  const btn = e.target.querySelector("button[type=submit]");
  errorBox.style.display = "none";
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  btn.disabled = true;
  btn.textContent = "Signing in...";
  try {
    await signInWithEmailAndPassword(auth, `${username}@${CUSTOMER_EMAIL_DOMAIN}`, password);
  } catch (err) {
    errorBox.textContent = "Invalid username or password";
    errorBox.style.display = "block";
    btn.disabled = false;
    btn.textContent = "Sign In";
  }
});

document.getElementById("logoutBtn").addEventListener("click", () => signOut(auth));

onAuthStateChanged(auth, async (user) => {
  clearListeners();
  if (!user) {
    currentRole = null;
    currentUid = null;
    loginView.style.display = "";
    appView.style.display = "none";
    document.getElementById("loginForm").querySelector("button[type=submit]").disabled = false;
    document.getElementById("loginForm").querySelector("button[type=submit]").textContent = "Sign In";
    return;
  }
  const tokenResult = await getIdTokenResult(user, true);
  currentRole = tokenResult.claims.role || "customer";
  currentUid = user.uid;
  loginView.style.display = "none";
  appView.style.display = "";
  renderNav();
  if (currentRole === "admin") {
    navigate("requests");
  } else {
    navigate("new-request");
  }
});

// ---------- nav ----------

function renderNav() {
  const links = currentRole === "admin"
    ? [["requests", "Requests"], ["customers", "Customers"]]
    : [["new-request", "New Request"], ["my-requests", "My Requests"]];
  navLinks.innerHTML = links
    .map(([id, label]) => `<a href="#" class="nav-link" data-nav="${id}">${label}</a>`)
    .join("");
  navLinks.querySelectorAll("[data-nav]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      navigate(el.dataset.nav);
    });
  });
}

function navigate(view) {
  clearListeners();
  navLinks.querySelectorAll("[data-nav]").forEach((el) => {
    el.classList.toggle("active", el.dataset.nav === view);
  });
  if (view === "new-request") renderNewRequest();
  else if (view === "my-requests") renderMyRequests();
  else if (view === "requests") renderAdminRequests();
  else if (view === "customers") renderAdminCustomers();
}

// ---------- customer: new request ----------

function renderNewRequest() {
  page.innerHTML = `
    <h2 class="page-title">New Request</h2>
    <div id="banner"></div>
    <form id="reqForm" class="stack card" style="max-width:480px">
      <div class="field"><label>Product / Material *</label><input id="material" required></div>
      <div class="field"><label>Quantity</label><input id="quantity"></div>
      <div class="field"><label>Unit</label>
        <select id="unit"><option>kg</option><option>mtr</option><option>pcs</option><option>ltr</option></select>
      </div>
      <div class="field"><label>Specifications</label><textarea id="specs"></textarea></div>
      <div class="field"><label>Additional Notes</label><textarea id="notes"></textarea></div>
      <button type="submit" class="btn btn-primary">Send Requirement</button>
    </form>`;
  document.getElementById("reqForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const banner = document.getElementById("banner");
    const btn = e.target.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      await addDoc(collection(db, "requests"), {
        customerId: currentUid,
        material: document.getElementById("material").value.trim(),
        quantity: document.getElementById("quantity").value.trim(),
        unit: document.getElementById("unit").value,
        specs: document.getElementById("specs").value.trim(),
        notes: document.getElementById("notes").value.trim(),
        status: "received",
        createdAt: Date.now(),
      });
      banner.innerHTML = `<div class="success-msg">Requirement sent. We will get back to you shortly.</div>`;
      e.target.reset();
    } catch (err) {
      banner.innerHTML = `<div class="error-msg">${err.message}</div>`;
    }
    btn.disabled = false;
  });
}

// ---------- customer: my requests ----------

function renderMyRequests() {
  page.innerHTML = `<h2 class="page-title">My Requests</h2><div id="list">Loading...</div>`;
  const q = query(collection(db, "requests"), where("customerId", "==", currentUid), orderBy("createdAt", "desc"));
  const unsub = onSnapshot(q, (snap) => {
    const list = document.getElementById("list");
    if (snap.empty) {
      list.innerHTML = `<p class="muted">You haven't submitted any requirements yet.</p>`;
      return;
    }
    list.innerHTML = snap.docs.map((d) => requestRowHtml(d.data())).join("");
  });
  unsubscribers.push(unsub);
}

function requestRowHtml(r) {
  return `
    <div class="card" style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between">
        <strong>${r.material}</strong>
        <span class="badge">${statusLabel(r.status).toUpperCase()}</span>
      </div>
      ${r.specs ? `<div class="muted">${r.specs}</div>` : ""}
      ${r.quantity ? `<div class="muted">${r.quantity} ${r.unit || ""}</div>` : ""}
      ${r.expectedDispatchDate ? `<div class="muted">Expected dispatch: ${r.expectedDispatchDate}</div>` : ""}
      ${r.transportName ? `<div class="muted">Transport: ${r.transportName}</div>` : ""}
      ${r.lrNumber ? `<div class="muted">LR / Tracking: ${r.lrNumber}</div>` : ""}
      ${r.adminNotes ? `<div class="muted">Note from us: ${r.adminNotes}</div>` : ""}
    </div>`;
}

// ---------- admin: requests ----------

function renderAdminRequests() {
  page.innerHTML = `<h2 class="page-title">Requests</h2><div id="list">Loading...</div>`;
  const q = query(collection(db, "requests"), orderBy("createdAt", "desc"));
  const unsub = onSnapshot(q, (snap) => {
    const list = document.getElementById("list");
    if (snap.empty) {
      list.innerHTML = `<p class="muted">No requests found.</p>`;
      return;
    }
    list.innerHTML = snap.docs.map((d) => adminRequestRowHtml(d.id, d.data())).join("");
    list.querySelectorAll("[data-open-request]").forEach((el) => {
      el.addEventListener("click", () => renderRequestDetail(el.dataset.openRequest));
    });
  });
  unsubscribers.push(unsub);
}

function adminRequestRowHtml(id, r) {
  return `
    <div class="card clickable" data-open-request="${id}" style="margin-bottom:8px;display:flex;justify-content:space-between">
      <div>
        <strong>${r.material}</strong>
        <div class="muted">${r.companyName || ""}</div>
      </div>
      <span class="badge">${statusLabel(r.status).toUpperCase()}</span>
    </div>`;
}

function renderRequestDetail(id) {
  clearListeners();
  const unsub = onSnapshot(doc(db, "requests", id), (snap) => {
    const r = snap.data();
    if (!r) return;
    page.innerHTML = `
      <a href="#" id="back" class="nav-link">&larr; Back</a>
      <h2 class="page-title">${r.material}</h2>
      <div class="muted">${r.companyName || ""}</div>
      ${r.specs ? `<p><strong>Specs</strong><br>${r.specs}</p>` : ""}
      ${r.notes ? `<p><strong>Customer Notes</strong><br>${r.notes}</p>` : ""}
      <form id="detailForm" class="stack card" style="max-width:480px">
        <div class="field"><label>Status</label>
          <select id="status">${STATUS_OPTIONS.map((s) => `<option value="${s}" ${s === r.status ? "selected" : ""}>${statusLabel(s)}</option>`).join("")}</select>
        </div>
        <div class="field"><label>Note for customer</label><input id="adminNotes" value="${r.adminNotes || ""}"></div>
        <div class="field"><label>Transport</label><input id="transportName" value="${r.transportName || ""}"></div>
        <div class="field"><label>LR No.</label><input id="lrNumber" value="${r.lrNumber || ""}"></div>
        <div class="field"><label>Expected Dispatch (YYYY-MM-DD)</label><input id="expectedDispatchDate" value="${r.expectedDispatchDate || ""}" placeholder="2026-08-15"></div>
        <button type="submit" class="btn btn-primary">Save Changes</button>
      </form>`;
    document.getElementById("back").addEventListener("click", (e) => { e.preventDefault(); navigate("requests"); });
    document.getElementById("detailForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      await updateDoc(doc(db, "requests", id), {
        status: document.getElementById("status").value,
        adminNotes: document.getElementById("adminNotes").value.trim(),
        transportName: document.getElementById("transportName").value.trim(),
        lrNumber: document.getElementById("lrNumber").value.trim(),
        expectedDispatchDate: document.getElementById("expectedDispatchDate").value.trim(),
      });
      navigate("requests");
    });
  });
  unsubscribers.push(unsub);
}

// ---------- admin: customers ----------

function renderAdminCustomers() {
  page.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h2 class="page-title">Customers</h2>
      <button id="addCustomerBtn" class="btn btn-primary">+ Add Customer</button>
    </div>
    <div id="banner"></div>
    <div id="addCustomerForm" style="display:none"></div>
    <div id="list">Loading...</div>`;
  document.getElementById("addCustomerBtn").addEventListener("click", showAddCustomerForm);
  const unsub = onSnapshot(collection(db, "customers"), (snap) => {
    const list = document.getElementById("list");
    const customers = snap.docs.filter((d) => d.data().role !== "admin");
    if (customers.length === 0) {
      list.innerHTML = `<p class="muted">No customers yet.</p>`;
      return;
    }
    list.innerHTML = customers.map((d) => `
      <div class="card clickable" data-open-customer="${d.id}" style="margin-bottom:8px">
        <strong>${d.data().companyName}</strong>
        <div class="muted">${d.data().username}</div>
      </div>`).join("");
    list.querySelectorAll("[data-open-customer]").forEach((el) => {
      el.addEventListener("click", () => renderCustomerDetail(el.dataset.openCustomer));
    });
  });
  unsubscribers.push(unsub);
}

function showAddCustomerForm() {
  const form = document.getElementById("addCustomerForm");
  form.style.display = "";
  form.innerHTML = `
    <form id="addForm" class="stack card" style="max-width:480px;margin-bottom:16px">
      <div class="field"><label>Company Name *</label><input id="companyName" required></div>
      <div class="field"><label>Contact Name</label><input id="contactName"></div>
      <div class="field"><label>Phone</label><input id="phone"></div>
      <div class="field"><label>Username *</label><input id="newUsername" required></div>
      <div class="field"><label>Password *</label><input id="newPassword" type="password" required></div>
      <button type="submit" class="btn btn-primary">Create Customer Login</button>
    </form>`;
  document.getElementById("addForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const banner = document.getElementById("banner");
    const btn = e.target.querySelector("button[type=submit]");
    btn.disabled = true;
    try {
      await adminFetch("/api/admin/customers", "POST", {
        company_name: document.getElementById("companyName").value.trim(),
        contact_name: document.getElementById("contactName").value.trim(),
        phone: document.getElementById("phone").value.trim(),
        username: document.getElementById("newUsername").value.trim(),
        password: document.getElementById("newPassword").value,
      });
      form.style.display = "none";
      form.innerHTML = "";
    } catch (err) {
      banner.innerHTML = `<div class="error-msg">${err.message}</div>`;
    }
    btn.disabled = false;
  });
}

function renderCustomerDetail(uid) {
  clearListeners();
  const unsub = onSnapshot(doc(db, "customers", uid), (snap) => {
    const c = snap.data();
    if (!c) return;
    page.innerHTML = `
      <a href="#" id="back" class="nav-link">&larr; Back</a>
      <h2 class="page-title">${c.companyName}</h2>
      <div id="banner"></div>
      <form id="editForm" class="stack card" style="max-width:480px">
        <div class="field"><label>Company Name *</label><input id="companyName" value="${c.companyName || ""}" required></div>
        <div class="field"><label>Contact Name</label><input id="contactName" value="${c.contactName || ""}"></div>
        <div class="field"><label>Phone</label><input id="phone" value="${c.phone || ""}"></div>
        <div class="field"><label>Username</label><input value="${c.username}" disabled></div>
        <div class="field"><label>Reset Password</label><input id="newPassword" type="password" placeholder="Leave blank to keep current"></div>
        <button type="submit" class="btn btn-primary">Save Changes</button>
      </form>
      <div class="card" style="margin-top:24px;border-color:var(--danger)">
        <h3 style="color:var(--danger)">Danger Zone</h3>
        <p class="muted">Permanently delete this customer's login and all of their submitted requests. This cannot be undone.</p>
        <button id="deleteBtn" class="btn" style="border:1px solid var(--danger);color:var(--danger);background:none">Delete Customer</button>
      </div>`;
    document.getElementById("back").addEventListener("click", (e) => { e.preventDefault(); navigate("customers"); });
    document.getElementById("editForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const banner = document.getElementById("banner");
      try {
        const newPassword = document.getElementById("newPassword").value;
        await adminFetch(`/api/admin/customers/${uid}`, "PATCH", {
          company_name: document.getElementById("companyName").value.trim(),
          contact_name: document.getElementById("contactName").value.trim(),
          phone: document.getElementById("phone").value.trim(),
          ...(newPassword ? { password: newPassword } : {}),
        });
        banner.innerHTML = `<div class="success-msg">Changes saved.</div>`;
      } catch (err) {
        banner.innerHTML = `<div class="error-msg">${err.message}</div>`;
      }
    });
    document.getElementById("deleteBtn").addEventListener("click", async () => {
      if (!confirm(`Permanently delete "${c.companyName}"? This removes their login and every request they've submitted. This cannot be undone.`)) return;
      await adminFetch(`/api/admin/customers/${uid}`, "DELETE");
      navigate("customers");
    });
  });
  unsubscribers.push(unsub);
}
