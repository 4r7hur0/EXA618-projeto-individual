import { Link, Outlet } from "react-router-dom";

export function Layout() {
  return (
    <>
      <nav className="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
        <div className="container">
          <Link className="navbar-brand" to="/">
            Aparelhos
          </Link>
          <button
            className="navbar-toggler"
            type="button"
            data-bs-toggle="collapse"
            data-bs-target="#navMain"
            aria-controls="navMain"
            aria-expanded="false"
            aria-label="Menu"
          >
            <span className="navbar-toggler-icon" />
          </button>
          <div className="collapse navbar-collapse" id="navMain">
            <ul className="navbar-nav ms-auto">
              <li className="nav-item">
                <Link className="nav-link" to="/">
                  Buscar modelo
                </Link>
              </li>
              <li className="nav-item">
                <Link className="nav-link" to="/explorar">
                  Explorar ofertas
                </Link>
              </li>
            </ul>
          </div>
        </div>
      </nav>
      <main className="container pb-5">
        <Outlet />
      </main>
    </>
  );
}
