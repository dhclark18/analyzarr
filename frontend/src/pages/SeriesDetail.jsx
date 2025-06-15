import React, { useEffect, useState } from 'react';
import { useParams, Link }           from 'react-router-dom';
import {
  Container,
  Table,
  Spinner,
  Alert,
  Button
} from 'react-bootstrap';
import Layout                          from '../components/Layout';
import './SeriesDetail.css';

export default function SeriesDetail() {
  const { seriesTitle } = useParams();
  const [episodesBySeason, setEpisodesBySeason] = useState({});
  const [loading, setLoading]                 = useState(true);
  const [error, setError]                     = useState(null);
  const [replacing, setReplacing]             = useState({});

  useEffect(() => {
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
      .catch(err => setError(err))
      .finally(() => setLoading(false));
  }, [seriesTitle]);

  const replaceEpisode = ({ seriesId, episodeId }) => {
    setReplacing(prev => ({ ...prev, [episodeId]: true }));
    fetch('/api/episodes/replace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ series_id: seriesId, episode_id: episodeId })
    })
    .then(res => {
      if (!res.ok) throw new Error(res.statusText);
      return res.json();
    })
    .then(() => window.location.reload())
    .catch(err => {
      console.error(err);
      setReplacing(prev => ({ ...prev, [episodeId]: false }));
    });
  };

  if (loading) {
    return (
      <Layout>
        <Container className="py-4 text-center">
          <Spinner animation="border" role="status" />
        </Container>
      </Layout>
    );
  }
  if (error) {
    return (
      <Layout>
        <Container className="py-4">
          <Alert variant="danger">Error: {error.toString()}</Alert>
          <Button as={Link} to="/" variant="outline-light" className="mt-2">
            ← Back
          </Button>
        </Container>
      </Layout>
    );
  }

  return (
    <Layout>
      <Container fluid className="py-4">
        <Button as={Link} to="/" variant="outline-light" className="mb-3">
          ← Back
        </Button>
        <div className="table-wrapper">
          {Object.keys(episodesBySeason)
            .sort((a,b) => a-b)
            .map(seasonNum => (
              <section key={seasonNum} className="season-block mb-5">
                <h2 className="page-subtitle mb-3">Season {seasonNum}</h2>
                <Table striped hover responsive variant="dark">
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
                    {episodesBySeason[seasonNum].map(ep => (
                      <tr key={ep.key}>
                        <td>{ep.matches ? '✅' : '❌'}</td>
                        <td>{ep.code}</td>
                        <td>{ep.expectedTitle}</td>
                        <td>{ep.actualTitle}</td>
                        <td>{ep.confidence}</td>
                        <td>
                          <Button
                            variant="warning"
                            size="sm"
                            disabled={replacing[ep.episodeId]}
                            onClick={() => replaceEpisode({ seriesId: ep.seriesId, episodeId: ep.episodeId })}
                          >
                            {replacing[ep.episodeId] ? 'Replacing…' : 'Replace'}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </section>
            ))}
        </div>
      </Container>
    </Layout>
  );
}
