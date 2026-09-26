import { api, usePoll } from "./api";
import { useRoute } from "./router";
import Cast from "./screens/Cast";
import Characters from "./screens/Characters";
import Clips from "./screens/Clips";
import Home from "./screens/Home";
import Library from "./screens/Library";
import Overview from "./screens/Overview";
import Series from "./screens/Series";
import Settings from "./screens/Settings";
import Share from "./screens/Share";
import Transcript from "./screens/Transcript";
import Translate from "./screens/Translate";
import Voice from "./screens/Voice";
import Mix from "./screens/Mix";
import Sidebar from "./shell/Sidebar";
import StatusBar from "./shell/StatusBar";
import TopBar from "./shell/TopBar";

export default function App() {
  const route = useRoute();
  const state = usePoll(api.state, [], 5000);
  const projects = usePoll(api.projects, [], 8000);
  const series = usePoll(api.seriesList, [], 15000);
  const libs = usePoll(api.libraries, [], 30000);
  // lists are brief rows; the open project's full summary is fetched on its own
  const open = usePoll(() => (route.project ? api.project(route.project) : Promise.resolve(null)), [route.project], 8000);
  const list = projects.data ?? [];
  const seriesList = series.data ?? [];
  const project = open.data && open.data.id === route.project ? open.data : null;
  const refresh = () => { void projects.reload(); void series.reload(); void open.reload(); void libs.reload(); };

  let body;
  if (route.settings) body = <Settings state={state.data} onSaved={() => void state.reload()} />;
  else if (route.share) body = <Share key={route.share} id={route.share} />;
  else if (route.cast) body = <Cast key={route.cast} id={route.cast} />;
  else if (route.clips) body = <Clips seriesId={route.clips.series} series={seriesList} projects={list} />;
  else if (route.library) body = <Library key={route.library} id={route.library} state={state.data} onChanged={refresh} />;
  else if (route.series) body = <Series key={route.series} id={route.series} state={state.data} onChanged={refresh} />;
  else if (!route.project || open.error) body = <Home projects={list} series={seriesList} libraries={libs.data ?? []} state={state.data} reload={refresh} />;
  else if (!project) body = null;
  else if (route.screen === "characters") body = <Characters key={project.id} project={project} onChanged={refresh} />;
  else if (route.screen === "transcript") body = <Transcript key={project.id} project={project} onChanged={refresh} />;
  else if (route.screen === "translate") body = <Translate key={project.id} project={project} state={state.data} onChanged={refresh} />;
  else if (route.screen === "voice") body = <Voice key={project.id} project={project} state={state.data} onChanged={refresh} />;
  else if (route.screen === "mix") body = <Mix key={project.id} project={project} onChanged={refresh} />;
  else body = <Overview key={project.id} project={project} state={state.data} onChanged={refresh} />;

  return (
    <div className="h-full flex flex-col">
      <TopBar project={project} screen={route.screen} settingsOpen={!!route.settings} />
      <div className="flex-1 flex min-h-0">
        <Sidebar projects={list} series={seriesList} libraries={libs.data ?? []} project={project} screen={route.screen}
          openSeries={route.series ?? null} openLibrary={route.library ?? null} clipsOpen={!!route.clips} />
        <main className="flex-1 min-w-0 min-h-0 overflow-y-auto flex flex-col">
          {projects.error && <div className="m-16 p-10 border border-bad bg-badbg text-bad rounded-3 text-11.5">API unreachable: {projects.error}</div>}
          {body}
        </main>
      </div>
      <StatusBar state={state.data} />
    </div>
  );
}
