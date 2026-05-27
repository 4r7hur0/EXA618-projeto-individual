import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AparelhoDetalhePage } from "./pages/AparelhoDetalhe";
import { AparelhosLista } from "./pages/AparelhosLista";
import { Home } from "./pages/Home";
import { OfertaDetalhePage } from "./pages/OfertaDetalhe";
import { OfertasLista } from "./pages/OfertasLista";
import { ExplorarOfertas } from "./pages/ExplorarOfertas";
import { SearchResult } from "./pages/SearchResult";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="explorar" element={<ExplorarOfertas />} />
          <Route path="resultado/:termo" element={<SearchResult />} />
          <Route path="aparelhos" element={<AparelhosLista />} />
          <Route path="aparelhos/:id" element={<AparelhoDetalhePage />} />
          <Route path="ofertas" element={<OfertasLista />} />
          <Route path="ofertas/:id" element={<OfertaDetalhePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
