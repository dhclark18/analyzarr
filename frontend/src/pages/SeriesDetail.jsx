import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Container, Table, Spinner, Alert, Button, ProgressBar } from 'react-bootstrap';
import Layout from '../components/Layout';
import './SeriesDetail.css';

export default function SeriesDetail() {
  const { seriesTitle } = useParams();
  const [episodesBySeason, setEpisodesBySeason] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [jobs, setJobs] = useState({}); // per-episode job status

  const loadEpisodes = () => {
    setLoading(true);
    setError(null);
    fetch(`/api/series/${encodeURIComponent(seriesTitle)}/episodes`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(data => {
        const grouped = data.reduce((acc, ep) => {
          const s = ep.season;
          (acc[s] = acc[s] || []).push(ep);
          return acc;
        }, {});
        setEpisodesBySeason(grouped);
      })
      .catch(err => setError(err.toString()))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadEpisodes(); }, [seriesTitle]);

  // --- Start a replace job ---
const replaceEpisode = async (key) => {
  // initialize job state
  setJobs(prev => ({
    ...prev,
    [key]: { status: 'queued', progress: 0, message: 'Queued…' }
  }));

  try {
    // enqueue job
    const res = await fetch('/api/episodes/replace-async', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key })
    });
    const data = await res.json();
    if (!data.job_id) throw new Error('No job_id returned');
    const jobId = data.job_id;

    // poll job status every 2s
    const interval = setInterval(async () => {
      try {
        const r = await fetch(`/api/job-status/${jobId}`);
        if (!r.ok) throw new Error(`Status fetch failed: ${r.status}`);
        const status = await r.json();

        // map Flask job fields to frontend
        const mapped = {
          status: status.status,           // running, queued, done, error
          progress: status.progress || 0, // 0–100
          message: status.message || '',   // current message
        };
        setJobs(prev => ({ ...prev, [key]: mapped }));

        // stop polling when done/error
        if (mapped.status === 'done' || mapped.status === 'error') {
          clearInterval(interval);
          loadEpisodes(); // refresh episode data
        }
      } catch (err) {
        console.error('Error fetching job status:', err);
        clearInterval(interval);
        setJobs(prev => ({
          ...prev,
          [key]: { status: 'error', message: err.toString(), progress: 0 }
        }));
      }
    }, 2000);

  } catch (err) {
    console.error('Replace job error:', err);
    setJobs(prev => ({
      ...prev,
      [key]: { status: 'error', message: err.toString(), progress: 0 }
    }));
  }
};

  const overrideEpisode = async (key) => {
    setJobs(prev => ({ ...prev, [key]: { ...prev[key], status: 'overriding' } }));
    try {
      await fetch(`/api/episode/${encodeURIComponent(key)}/tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: 'override' })
      });
      await fetch(`/api/episode/${encodeURIComponent(key)}/tags/problematic-episode`, { method: 'DELETE' });
      loadEpisodes();
    } catch (err) {
      console.error(err);
    } finally {
      setJobs(prev => ({ ...prev, [key]: { ...prev[key], status: 'idle' } }));
    }
  };

  if (loading) return (
    <Layout>
      <Container className="py-4 text-center"><Spinner animation="border" role="status" /></Container>
    </Layout>
  );

  if (error) return (
    <Layout>
      <Container className="py-4">
        <Alert variant="danger">Error: {error.toString()}</Alert>
        <Button as={Link} to="/" variant="outline-light" className="mt-2">← Back</Button>
      </Container>
    </Layout>
  );

  return (
    <Layout>
      <Container fluid className="py-4">
        <Button as={Link} to="/" variant="outline-light" className="mb-3">← Back</Button>
        <div className="table-wrapper">
          {Object.keys(episodesBySeason).sort((a,b)=>a-b).map(seasonNum => (
            <section key={seasonNum} className="season-block mb-5">
              <h2 className="page-subtitle mb-3">Season {seasonNum}</h2>
              <Table striped hover responsive className="table">
                <thead>
                  <tr>
                    <th>Match?</th>
                    <th>Code</th>
                    <th>Expected Title</th>
                    <th>Actual Title</th>
                    <th>Confidence</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {episodesBySeason[seasonNum].map(ep => {
                    const job = jobs[ep.key] || {};
                    const inProgress = job.status === 'running' || job.status === 'queued' || job.status === 'overriding';
                    return (
                      <tr key={ep.key}>
                        <td>{ep.matches ? '✅' : '❌'}</td>
                        <td>{ep.code}</td>
                        <td>
                          <Button
                            variant="link"
                            as={Link}
                            to={`/episode/${encodeURIComponent(ep.key)}`}
                            className="p-0 expected-link text-light"
                          >
                            {ep.expectedTitle}
                          </Button>
                        </td>
                        <td>{ep.actualTitle}</td>
                        <td>{ep.confidence}</td>
                        <td>
                          {!ep.matches && (
                            <>
                              <Button
                                variant="warning"
                                size="sm"
                                disabled={inProgress}
                                onClick={() => replaceEpisode(ep.key)}
                                className="me-2"
                              >
                                {inProgress && job.status==='running' ? 'Replacing…' :
                                 inProgress && job.status==='queued' ? 'Queued…' :
                                 'Replace'}
                              </Button>
                              <Button
                                variant="secondary"
                                size="sm"
                                disabled={inProgress}
                                onClick={() => overrideEpisode(ep.key)}
                              >
                                {inProgress && job.status==='overriding' ? 'Overriding…' : 'Override'}
                              </Button>
                              {/* Show progress + log only while running */}
                              {inProgress && job.progress !== undefined && (
                                <>
                                  <ProgressBar
                                    now={job.progress}
                                    label={`${job.progress || 0}%`}
                                    striped
                                    animated
                                    className="mt-1"
                                  />
                                  {job.message && <div className="text-muted small">{job.message}</div>}
                                </>
                              )}
                            </>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </Table>
            </section>
          ))}
        </div>
      </Container>
    </Layout>
  );
}
