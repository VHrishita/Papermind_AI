import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js";
import {
  getAuth,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword
} from "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth.js";

const firebaseConfig = {
  apiKey: "AIzaSyD6v0_m0ATpVd_Inrt36aAEJ0hsBPiJCfA",
  authDomain: "papermind-f9700.firebaseapp.com",
  projectId: "papermind-f9700",
  storageBucket: "papermind-f9700.firebasestorage.app",
  messagingSenderId: "800293662098",
  appId: "1:800293662098:web:6f6c8e305d620311c2654b",
  measurementId: "G-65Z53STJH3"
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);

// SIGNUP
window.signup = async function () {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;

  try {
    await createUserWithEmailAndPassword(auth, email, password);
    alert("Signup successful!");
    window.location.href = "app.html";
  } catch (error) {
    alert(error.message);
  }
};

// LOGIN
window.login = async function () {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;

  try {
    await signInWithEmailAndPassword(auth, email, password);
    alert("Login successful!");
    window.location.href = "app.html";
  } catch (error) {
    alert(error.message);
  }
};